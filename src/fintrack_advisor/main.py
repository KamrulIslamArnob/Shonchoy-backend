import asyncio
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langsmith import tracing_context
from pydantic import StringConstraints

from fintrack_advisor.config import Settings
from fintrack_advisor.graph import build_graph
from fintrack_common.api import DTO, Result, envelope, make_app, require_dev_key


class RunCreate(DTO):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class RunRead(DTO):
    mode: Literal["offline_stub"] = "offline_stub"
    answer: str
    steps: list[str]


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    app = make_app("FinTrack isolated advisor API")
    app.state.graph = build_graph()
    bearer = HTTPBearer(auto_error=False)

    def access(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        require_dev_key(config.dev_api_key, credentials.credentials if credentials else None)

    @app.get("/v1/health/ready", dependencies=[Depends(access)], tags=["health"])
    def ready() -> dict[str, str]:
        return {"status": "ready", "mode": "offline_stub"}

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
