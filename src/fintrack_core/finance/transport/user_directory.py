"""Bounded lookup of verified managed users for the people picker."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from fintrack_common.api import DTO, Result
from fintrack_core.database import auth_session
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import result
from fintrack_core.user_directory import search_users

router = APIRouter(tags=["user directory"])


class DirectoryUser(DTO):
    id: str
    name: str
    email: str


class DirectoryResult(DTO):
    items: list[DirectoryUser]


@router.get("/user-directory", response_model=Result[DirectoryResult])
def directory_search(
    request: Request,
    auth_db: Annotated[Session, Depends(auth_session)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> Result[Data]:
    return result(
        request,
        search_users(
            auth_db,
            request.state.auth_subject,
            q,
            request.app.state.settings.directory_test_user_ids,
        ),
    )
