import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from fintrack_advisor.privacy import Capability
from fintrack_advisor.providers import HostedProvider, ProviderError


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_provider_receives_only_generic_prompts(kind: str) -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if kind == "openai":
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Generic explanation"}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "Generic explanation"}]}
        )

    provider = HostedProvider(
        kind,  # type: ignore[arg-type]
        "test-model",
        SecretStr("dummy-key"),
        transport=httpx.MockTransport(respond),
    )
    assert asyncio.run(provider.explain(Capability.SPENDING)) == "Generic explanation"
    request = captured[0]
    payload = json.loads(request.content)
    assert request.url.path.endswith("/responses" if kind == "openai" else "/messages")
    assert "Alice" not in request.content.decode()
    assert "123456" not in request.content.decode()
    assert "dummy-key" not in request.content.decode()
    if kind == "openai":
        assert payload["store"] is False


def test_provider_failure_does_not_expose_secret() -> None:
    provider = HostedProvider(
        "openai",
        "test-model",
        SecretStr("dummy-key"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="dummy-key")),
    )
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.explain(Capability.INCOME))
    assert "dummy-key" not in str(error.value)


def test_provider_rejects_raw_user_input_and_insecure_urls() -> None:
    provider = HostedProvider("openai", "test-model", SecretStr("dummy-key"))
    with pytest.raises(ValueError, match="Unsupported capability"):
        asyncio.run(provider.explain("Alice BDT 123456"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="HTTPS"):
        HostedProvider(
            "openai", "test-model", SecretStr("dummy-key"), base_url="http://example.test"
        )
