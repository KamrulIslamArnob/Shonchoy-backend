import re
from collections.abc import Iterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from fintrack_common.api import Page, Result, require_dev_key
from fintrack_core.auth import authenticated_access
from fintrack_core.database import session
from fintrack_core.feedback.schemas import (
    FeedbackCategoryCreate,
    FeedbackCategoryEdit,
    FeedbackCategoryRead,
    FeedbackContext,
    FeedbackEntryCreate,
    FeedbackEntryRead,
    FeedbackOrigin,
    FeedbackReceipt,
    FeedbackSummary,
    Key,
)
from fintrack_core.feedback.service import FeedbackService
from fintrack_core.finance.domain import Data, DomainError
from fintrack_core.finance.http import Key as CommandKey
from fintrack_core.finance.http import Limit, result
from fintrack_core.finance.persistence import DEV_SCOPE
from fintrack_core.routes import bearer


def admin_access(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> None:
    require_dev_key(
        request.app.state.settings.feedback_admin_key,
        credentials.credentials if credentials else None,
    )


def service(
    request: Request,
    db: Annotated[Session, Depends(session)],
    actor: Annotated[
        str, Header(alias="X-Feedback-Actor", pattern=r"^[A-Za-z0-9:_-]{1,80}$")
    ] = "development-admin",
) -> Iterator[FeedbackService]:
    if not request.app.state.core_capacity.acquire(timeout=2):
        raise HTTPException(503, "Feedback is busy. Retry with the same command key.")
    try:
        token = request.app.state.settings.command_fingerprint_key
        scope = UUID(getattr(request.state, "core_scope_id", str(DEV_SCOPE)))
        yield FeedbackService(db, token.get_secret_value() if token else "", actor, scope=scope)
    except DomainError as error:
        raise HTTPException(error.status, error.detail) from None
    finally:
        request.app.state.core_capacity.release()


def version(value: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    if value is None:
        raise HTTPException(428, "If-Match is required. Reload the category before saving.")
    if not re.fullmatch(r'"[1-9][0-9]{0,8}"', value):
        raise HTTPException(422, "If-Match must contain a quoted category version.")
    return int(value[1:-1])


Service = Annotated[FeedbackService, Depends(service)]
public_router = APIRouter(
    prefix="/v1/core/feedback", dependencies=[Depends(authenticated_access)], tags=["feedback"]
)
admin_router = APIRouter(
    prefix="/v1/admin/feedback", dependencies=[Depends(admin_access)], tags=["feedback admin"]
)


@public_router.get("/context", response_model=Result[FeedbackContext])
def context(request: Request, feature: Key, svc: Service) -> Result[Data]:
    return result(request, svc.context(feature))


@public_router.post("/interest", response_model=Result[FeedbackReceipt], status_code=201)
def interest(request: Request, body: FeedbackOrigin, key: CommandKey, svc: Service) -> Result[Data]:
    return result(request, svc.interest(key, body))


@public_router.post("/entries", response_model=Result[FeedbackReceipt], status_code=201)
def submit(
    request: Request, body: FeedbackEntryCreate, key: CommandKey, svc: Service
) -> Result[Data]:
    return result(request, svc.submit(key, body))


@admin_router.get("/categories", response_model=Result[dict[str, list[FeedbackCategoryRead]]])
def categories(request: Request, svc: Service) -> Result[Data]:
    return result(request, svc.categories())


@admin_router.post("/categories", response_model=Result[FeedbackCategoryRead], status_code=201)
def create_category(
    request: Request, body: FeedbackCategoryCreate, key: CommandKey, svc: Service
) -> Result[Data]:
    return result(request, svc.save_category(key, body))


@admin_router.patch("/categories/{identifier}", response_model=Result[FeedbackCategoryRead])
def edit_category(
    request: Request,
    identifier: UUID,
    body: FeedbackCategoryEdit,
    key: CommandKey,
    svc: Service,
    expected: Annotated[int, Depends(version)],
) -> Result[Data]:
    return result(request, svc.save_category(key, body, identifier, expected))


@admin_router.get("/entries", response_model=Result[Page[FeedbackEntryRead]])
def entries(
    request: Request,
    svc: Service,
    kind: Literal["feedback", "interest"] = "feedback",
    feature: Key | None = None,
    segment: Key | None = None,
    category: UUID | None = None,
    limit: Limit = 50,
    cursor: UUID | None = None,
) -> Result[Data]:
    return result(request, svc.entries(kind, feature, segment, category, limit, cursor))


@admin_router.get("/summary", response_model=Result[FeedbackSummary])
def summary(
    request: Request, svc: Service, feature: Key | None = None, segment: Key | None = None
) -> Result[Data]:
    return result(request, svc.summary(feature, segment))
