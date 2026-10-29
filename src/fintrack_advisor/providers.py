"""Hosted model adapters whose only input is a fixed generic capability."""

from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from fintrack_advisor.privacy import SYSTEM_PROMPT, Capability, model_prompt


class ProviderError(Exception):
    """A provider failed without exposing request contents or credentials."""


class ProviderBalanceError(ProviderError):
    """The configured provider has insufficient credit."""


class HostedProvider:
    def __init__(
        self,
        kind: Literal["openai", "anthropic"],
        model: str,
        api_key: SecretStr,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if kind not in {"openai", "anthropic"}:
            raise ValueError("Unsupported provider")
        default = (
            "https://api.openai.com/v1" if kind == "openai" else "https://api.anthropic.com/v1"
        )
        url = urlsplit(base_url or default)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Provider base URL must be HTTPS without credentials or query")
        if not model.strip() or not api_key.get_secret_value().strip():
            raise ValueError("Provider model and API key are required")
        self.kind = kind
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or default).rstrip("/")
        self.transport = transport

    async def explain(self, capability: Capability) -> str:
        prompt = model_prompt(capability)
        if self.kind == "openai":
            path = "/responses"
            headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
            body = {
                "model": self.model,
                "instructions": SYSTEM_PROMPT,
                "input": prompt,
                "store": False,
                "max_output_tokens": 256,
            }
        else:
            path = "/messages"
            headers = {
                "x-api-key": self.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
            }
            body = {
                "model": self.model,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            }
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=15.0, follow_redirects=False
            ) as client:
                response = await client.post(self.base_url + path, headers=headers, json=body)
                response.raise_for_status()
                result = response.json()
            if self.kind == "openai":
                blocks = [
                    block
                    for item in result["output"]
                    if item.get("type") == "message"
                    for block in item.get("content", [])
                    if block.get("type") == "output_text"
                ]
            else:
                blocks = [block for block in result["content"] if block.get("type") == "text"]
            text = "".join(block["text"] for block in blocks).strip()
            if not text or len(text) > 4000:
                raise ValueError("Invalid provider response")
            return text
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError("The configured model provider is unavailable.") from None
