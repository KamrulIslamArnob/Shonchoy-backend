import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from fintrack_advisor.privacy import Capability
from fintrack_core.finance.transport import advisor


def test_gateway_sends_only_service_key_and_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"data": {"mode": "hosted_generic", "answer": "Generic explanation"}}
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        advisor.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(reply), **kwargs),
    )
    answer = asyncio.run(
        advisor.fetch_explanation(
            "http://localhost:8001", SecretStr("synthetic-key"), Capability.SPENDING
        )
    )
    assert answer == "Generic explanation"
    request = captured[0]
    assert json.loads(request.content) == {"capability": "spending"}
    assert request.headers["authorization"] == "Bearer synthetic-key"
    assert "x-neon-session-id" not in request.headers


def test_gateway_refuses_insecure_nonlocal_service() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            advisor.fetch_explanation(
                "http://external.example", SecretStr("synthetic-key"), Capability.SPENDING
            )
        )
    assert error.value.status_code == 503
