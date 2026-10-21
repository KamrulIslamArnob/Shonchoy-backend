from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from secrets import compare_digest
from typing import Any, Generic, TypeVar
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

T = TypeVar("T")


class DTO(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", from_attributes=True
    )

    @field_validator("*", mode="after")
    @classmethod
    def utc_datetimes(cls, value: Any) -> Any:
        # SQLite test adapters drop timezone metadata; the persistence contract is always UTC.
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class Result(DTO, Generic[T]):
    ok: bool = True
    data: T
    request_id: str


class Page(DTO, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Problem(DTO):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    request_id: str
    field_errors: list[dict[str, str]] | None = None


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": Problem, "description": detail, "content": {"application/problem+json": {}}}
    for code, detail in {
        401: "Unauthorized",
        404: "Not found",
        409: "Conflict",
        428: "Precondition required",
        422: "Validation error",
        503: "Unavailable",
        504: "Timeout",
    }.items()
}


def envelope(request: Request, data: T) -> Result[T]:
    return Result(data=data, request_id=request.state.request_id)


def require_dev_key(expected: SecretStr | None, supplied: str | None) -> None:
    if expected is None or len(expected.get_secret_value()) < 32:
        raise HTTPException(503, "Development API token is not configured.")
    if supplied is None or not compare_digest(
        supplied.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise HTTPException(401, "A valid development bearer token is required.")


def make_app(title: str, origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(
        title=title,
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        responses=ERROR_RESPONSES,
    )

    @app.middleware("http")
    async def correlation(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Generate server-owned IDs; never reflect untrusted headers into logs or responses.
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception:
            response = problem(request, 500, "An unexpected error occurred.")
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def problem(
        request: Request, status: int, detail: str, fields: list[dict[str, str]] | None = None
    ) -> JSONResponse:
        codes = {
            401: "unauthorized",
            404: "not_found",
            409: "conflict",
            428: "precondition_required",
            422: "validation_error",
            503: "unavailable",
            504: "timeout",
        }
        body = Problem(
            title="Request failed",
            status=status,
            code=codes.get(status, "request_failed"),
            detail=detail,
            request_id=request.state.request_id,
            field_errors=fields,
        )
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(
            body.model_dump(by_alias=True, exclude_none=True),
            status_code=status,
            media_type="application/problem+json",
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith("/v1/core/") and any(
            error["type"] == "missing" and error["loc"] == ("header", "Idempotency-Key")
            for error in exc.errors()
        ):
            return problem(request, 428, "Idempotency-Key is required for this command.")
        # Pydantic's raw errors include input values. Return only field paths and error types.
        fields = [
            {
                "field": "body.[unknown]"
                if e["type"] == "extra_forbidden"
                else ".".join(map(str, e["loc"])),
                "code": e["type"],
            }
            for e in exc.errors()
        ]
        return problem(request, 422, "Request validation failed.", fields)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return problem(request, 500, "An unexpected error occurred.")

    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            expose_headers=["X-Request-Id"],
        )

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    return app
