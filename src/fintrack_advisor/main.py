import asyncio
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langsmith import tracing_context
from pydantic import Field, StringConstraints, model_validator

from fintrack_advisor.config import ProviderSettings, Settings
from fintrack_advisor.graph import build_graph
from fintrack_advisor.narrative import NarrativeRequest, NarrativeResult, extract_narrative
from fintrack_advisor.privacy import Capability
from fintrack_advisor.providers import HostedProvider, ProviderBalanceError, ProviderError
from fintrack_common.api import DTO, Result, envelope, make_app, require_dev_key


class RunCreate(DTO):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class RunRead(DTO):
    mode: Literal["offline_stub"] = "offline_stub"
    answer: str
    steps: list[str]


class ExplanationRequest(DTO):
    capability: Capability


class ExplanationRead(DTO):
    mode: Literal["hosted_generic"] = "hosted_generic"
    answer: str


Minor = Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]


class AnalysisValues(DTO):
    expense_minor: Minor | None = None
    income_minor: Minor | None = None
    assets_minor: Minor | None = None
    liabilities_minor: Minor | None = None


class AnalysisRequest(DTO):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    intent: Literal["spending", "income", "cashflow", "net_worth"]
    currency: Literal["BDT", "USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "SGD", "AED"]
    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    values: AnalysisValues

    @model_validator(mode="after")
    def check_values(self) -> "AnalysisRequest":
        required = {
            "spending": {"expense_minor"},
            "income": {"income_minor"},
            "cashflow": {"expense_minor", "income_minor"},
            "net_worth": {"assets_minor", "liabilities_minor"},
        }
        if set(self.values.model_dump(exclude_none=True)) != required[self.intent]:
            raise ValueError("Values do not match the requested analysis")
        return self


def format_minor(value: int, currency: str) -> str:
    if currency == "JPY":
        return f"{currency} {value:,}"
    sign = "-" if value < 0 else ""
    major, minor = divmod(abs(value), 100)
    return f"{sign}{currency} {major:,}.{minor:02d}"


def required_minor(value: int | None) -> int:
    if value is None:
        raise ValueError("Missing validated financial value")
    return value


def local_analysis(body: AnalysisRequest) -> str:
    values = body.values
    if body.intent == "spending":
        amount = format_minor(required_minor(values.expense_minor), body.currency)
        return f"Your recorded spending for {body.month} is {amount}."
    if body.intent == "income":
        amount = format_minor(required_minor(values.income_minor), body.currency)
        return f"Your recorded income for {body.month} is {amount}."
    if body.intent == "cashflow":
        total = required_minor(values.income_minor) - required_minor(values.expense_minor)
        return f"Your recorded cash flow for {body.month} is {format_minor(total, body.currency)}."
    total = required_minor(values.assets_minor) - required_minor(values.liabilities_minor)
    return f"Your recorded net worth is {format_minor(total, body.currency)}."


def create_app(
    settings: Settings | None = None, provider_settings: ProviderSettings | None = None
) -> FastAPI:
    config = settings or Settings()
    provider_config = provider_settings or ProviderSettings()
    app = make_app("FinTrack isolated advisor API")
    app.state.graph = build_graph()
    app.state.provider = None
    if provider_config.provider != "disabled":
        key = (
            provider_config.openai_api_key
            if provider_config.provider == "openai"
            else provider_config.anthropic_api_key
        )
        if key and provider_config.model:
            app.state.provider = HostedProvider(
                provider_config.provider, provider_config.model, key, provider_config.base_url
            )
    bearer = HTTPBearer(auto_error=False)

    def access(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        require_dev_key(config.dev_api_key, credentials.credentials if credentials else None)

    @app.get("/v1/health/ready", dependencies=[Depends(access)], tags=["health"])
    def ready() -> dict[str, str]:
        return {"status": "ready", "mode": "offline_stub"}

    @app.post(
        "/v1/agent/explanation",
        response_model=Result[ExplanationRead],
        dependencies=[Depends(access)],
        tags=["agent"],
    )
    async def explanation(request: Request, body: ExplanationRequest) -> Result[ExplanationRead]:
        provider = request.app.state.provider
        if provider is None:
            raise HTTPException(503, "Model provider is not configured.")
        try:
            answer = await provider.explain(body.capability)
        except ProviderError:
            raise HTTPException(503, "Model provider is unavailable.") from None
        return envelope(request, ExplanationRead(answer=answer))

    @app.post(
        "/v1/agent/narrative-extraction",
        response_model=Result[NarrativeResult],
        dependencies=[Depends(access)],
        tags=["agent"],
    )
    async def narrative_extraction(
        request: Request, body: NarrativeRequest
    ) -> Result[NarrativeResult]:
        provider = request.app.state.provider
        if provider is None:
            raise HTTPException(503, "Model provider is not configured.")
        try:
            with tracing_context(enabled=False):
                extracted = await extract_narrative(provider, body.text)
        except ProviderBalanceError:
            raise HTTPException(402, "Model provider needs credit.") from None
        except ProviderError:
            raise HTTPException(503, "Model provider is unavailable.") from None
        return envelope(request, extracted)

    @app.post(
        "/v1/agent/analysis",
        response_model=Result[RunRead],
        dependencies=[Depends(access)],
        tags=["agent"],
    )
    def analysis(request: Request, body: AnalysisRequest) -> Result[RunRead]:
        return envelope(
            request, RunRead(answer=local_analysis(body), steps=["validate", "respond"])
        )

    @app.post(
        "/v1/agent/runs",
        response_model=Result[RunRead],
        dependencies=[Depends(access)],
        tags=["agent"],
    )
    async def run(request: Request, body: RunCreate) -> Result[RunRead]:
        try:
            async with asyncio.timeout(10):
                with tracing_context(enabled=False):
                    state = await app.state.graph.ainvoke(
                        {"message": body.message}, config={"recursion_limit": 8}
                    )
        except TimeoutError:
            raise HTTPException(504, "Agent run timed out.") from None
        except Exception:
            raise HTTPException(503, "Agent run is unavailable.") from None
        return envelope(request, RunRead(answer=state["answer"], steps=state["steps"]))

    return app
