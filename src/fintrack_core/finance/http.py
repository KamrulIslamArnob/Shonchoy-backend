"""HTTP dependencies and mapping; no route-level SQL or commit."""

import re
from collections.abc import Callable, Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from fintrack_common.api import Result, envelope
from fintrack_core.database import session
from fintrack_core.finance.domain import Data, DomainError
from fintrack_core.finance.ports import Reader, Repositories, UnitOfWork


def unit_of_work(
    request: Request, db: Annotated[Session, Depends(session)]
) -> Iterator[UnitOfWork]:
    if not request.app.state.core_capacity.acquire(timeout=2):
        raise HTTPException(503, "Core API is busy. Retry later with the same command key.")
    try:
        yield request.app.state.core_uow_factory(db)
    except DomainError as error:
        raise HTTPException(error.status, error.detail) from None
    finally:
        request.app.state.core_capacity.release()


def command_key(key: Annotated[str, Header(alias="Idempotency-Key")]) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
        raise HTTPException(422, "Invalid idempotency key.")
    return key


Uow = Annotated[UnitOfWork, Depends(unit_of_work)]
Key = Annotated[str, Depends(command_key)]
Limit = Annotated[int, Query(ge=1, le=100)]


def wire(value: Any) -> Any:
    if isinstance(value, dict):
        return {re.sub(r"_([a-z])", lambda m: m[1].upper(), k): wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def result(request: Request, value: Data) -> Result[Data]:
    return envelope(request, wire(value))


def command(
    request: Request,
    uow: UnitOfWork,
    key: str,
    operation: str,
    payload: Data,
    action: Callable[[Repositories], Data],
) -> Result[Data]:
    return result(request, uow.command(key, operation, payload, action))


def collection(repo: Reader, limit: int, cursor: UUID | None, filters: Data | None = None) -> Data:
    rows = repo.list(limit=limit + 1, cursor=str(cursor) if cursor else None, filters=filters)
    return {
        "items": rows[:limit],
        "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }
