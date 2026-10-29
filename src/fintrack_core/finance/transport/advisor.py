"""Authenticated relay for generic model explanations, without user data."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import SecretStr, StrictBool, StringConstraints, field_validator

from fintrack_advisor.narrative import NarrativeRequest, NarrativeResult
from fintrack_advisor.privacy import Capability
from fintrack_common.api import DTO, Result, envelope

router = APIRouter(tags=["advisor"])


class ExplanationRequest(DTO):
    capability: Capability
    consent: StrictBool

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Hosted processing requires consent")
        return value


class ExplanationRead(DTO):
    answer: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class AdvisorServiceReply(ExplanationRead):
    mode: Literal["hosted_generic"]


async def fetch_explanation(url: str, key: SecretStr, capability: Capability) -> str:
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise HTTPException(503, "Advisor service is not configured.")
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(
                url.rstrip("/") + "/v1/agent/explanation",
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={"capability": capability.value},
            )
            response.raise_for_status()
            answer = AdvisorServiceReply.model_validate(response.json()["data"]).answer
        return answer
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Advisor service is unavailable.") from None


async def fetch_narrative(url: str, key: SecretStr, body: NarrativeRequest) -> NarrativeResult:
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise HTTPException(503, "Advisor service is not configured.")
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(
                url.rstrip("/") + "/v1/agent/narrative-extraction",
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json=body.model_dump(by_alias=True),
            )
            if response.status_code == 402:
                raise HTTPException(402, "Model provider needs credit.")
            response.raise_for_status()
            return NarrativeResult.model_validate(response.json()["data"])
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Advisor service is unavailable.") from None


@router.post("/advisor/explanation", response_model=Result[ExplanationRead])
async def explanation(request: Request, body: ExplanationRequest) -> Result[ExplanationRead]:
    settings = request.app.state.settings
    if not settings.advisor_service_url or not settings.advisor_service_key:
        raise HTTPException(503, "Advisor service is not configured.")
    if not request.app.state.advisor_rate_limiter.allow(request.state.auth_subject):
        raise HTTPException(429, "Too many advisor requests. Try again shortly.")
    answer = await fetch_explanation(
        settings.advisor_service_url, settings.advisor_service_key, body.capability
    )
    return envelope(request, ExplanationRead(answer=answer))


@router.post("/advisor/narrative-extraction", response_model=Result[NarrativeResult])
async def narrative_extraction(request: Request, body: NarrativeRequest) -> Result[NarrativeResult]:
    settings = request.app.state.settings
    if not settings.advisor_service_url or not settings.advisor_service_key:
        raise HTTPException(503, "Advisor service is not configured.")
    if not request.app.state.advisor_rate_limiter.allow(request.state.auth_subject):
        raise HTTPException(429, "Too many advisor requests. Try again shortly.")
    result = await fetch_narrative(settings.advisor_service_url, settings.advisor_service_key, body)
    return envelope(request, result)
