import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from fintrack_advisor.config import ProviderSettings
from fintrack_advisor.config import Settings as AdvisorSettings
from fintrack_advisor.main import create_app
from fintrack_advisor.narrative import NarrativeRequest, NarrativeResult, extract_narrative
from fintrack_advisor.providers import HostedProvider, ProviderError
from fintrack_core.finance.transport import advisor

TOKEN = "synthetic-narrative-service-" + "a" * 40
STORY = "Rickshaw 30 taka and coffee 50 taka today."
ITEMS = [
    {
        "kind": "expense",
        "description": "Rickshaw",
        "amountMajor": "30",
        "category": "Transport",
        "date": "today",
    },
    {
        "kind": "expense",
        "description": "Coffee",
        "amountMajor": "50",
        "category": "Food",
        "date": "today",
    },
]


def reply_for(kind: str, text: str) -> dict:
    if kind == "openai":
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    return {"content": [{"type": "text", "text": text}]}


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_narrative_provider_receives_reviewed_text_without_user_credentials(kind: str, caplog):
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json=reply_for(kind, json.dumps({"items": ITEMS})))

    provider = HostedProvider(
        kind, "synthetic-model", SecretStr("dummy-provider"), transport=httpx.MockTransport(handler)
    )  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO):
        result = asyncio.run(extract_narrative(provider, STORY))
    assert result.items[0].amount_major == "30"
    assert len(result.items) == 2
    request = received[0]
    payload = json.loads(request.content)
    assert STORY in json.dumps(payload)
    assert "synthetic-session" not in str(request.headers)
    assert TOKEN not in str(request.headers)
    assert "x-neon-session-id" not in request.headers
    assert "tools" not in payload
    assert STORY not in caplog.text
    if kind == "openai":
        assert payload["store"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"items": [{**ITEMS[0], "amountMajor": 30}]},
        {"items": [{**ITEMS[0], "amountMajor": "0"}]},
        {"items": [{**ITEMS[0], "date": "2026-02-30"}]},
        {"items": [{**ITEMS[0], "kind": "transfer"}]},
        {"items": [{**ITEMS[0], "accountId": "secret"}]},
        {"items": ITEMS * 11},
        {"items": [{**ITEMS[0], "description": ""}]},
    ],
)
def test_invalid_model_output_is_rejected(payload):
    with pytest.raises(ValidationError):
        NarrativeResult.model_validate(payload)


def test_provider_error_is_sanitized():
    provider = HostedProvider(
        "openai",
        "model",
        SecretStr("dummy-provider"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text=STORY)),
    )
    with pytest.raises(ProviderError) as error:
        asyncio.run(extract_narrative(provider, STORY))
    assert STORY not in str(error.value)


def test_advisor_requires_both_confirmations_before_calling_provider():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=reply_for("openai", json.dumps({"items": ITEMS})))

    app = create_app(
        AdvisorSettings(_env_file=None, dev_api_key=SecretStr(TOKEN)),
        ProviderSettings(_env_file=None, provider="disabled"),
    )
    app.state.provider = HostedProvider(
        "openai", "model", SecretStr("dummy-provider"), transport=httpx.MockTransport(handler)
    )
    path = "/v1/agent/narrative-extraction"
    body = {"text": STORY, "consent": True}
    with TestClient(app) as client:
        assert client.post(path, json=body).status_code == 401
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert (
            client.post(path, headers=headers, json={**body, "consent": False}).status_code == 422
        )
        assert (
            client.post(path, headers=headers, json={**body, "identityReviewed": False}).status_code
            == 422
        )
        assert (
            client.post(
                path, headers=headers, json={**body, "identityReviewed": "true"}
            ).status_code
            == 422
        )
        assert not calls
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 200
        assert response.json()["data"]["items"] == ITEMS


def test_core_relay_strips_user_credentials(monkeypatch: pytest.MonkeyPatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": {"items": ITEMS}})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        advisor.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    body = NarrativeRequest(text=STORY, consent=True)
    result = asyncio.run(advisor.fetch_narrative("http://localhost:8001", SecretStr(TOKEN), body))
    assert len(result.items) == 2
    assert json.loads(captured[0].content) == {
        "text": STORY,
        "consent": True,
    }
    assert captured[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert "x-neon-session-id" not in captured[0].headers


def test_insufficient_provider_credit_is_distinguishable():
    from fintrack_advisor.providers import ProviderBalanceError

    provider = HostedProvider(
        "openai",
        "model",
        SecretStr("dummy-provider"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(402, json={"error": "private"})
        ),
    )
    with pytest.raises(ProviderBalanceError, match="needs credit"):
        asyncio.run(extract_narrative(provider, STORY))
