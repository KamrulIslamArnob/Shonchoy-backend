"""Recurring REST contract and use-case mapping."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Request

from fintrack_common.api import Page, Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import planning
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Limit, Uow, collection, command, result

router = APIRouter(tags=["core recurring"])


@router.post("/recurring", response_model=Result[s.RecurringRead], status_code=201)
def create_recurring(request: Request, body: s.RecurringCreate, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request, uow, key, "recurring.create", data, lambda r: planning.recurring(r, data)
    )


@router.get("/recurring", response_model=Result[Page[s.RecurringRead]])
def recurring_list(
    request: Request, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    return result(request, uow.read(lambda r: collection(r.recurring, limit, cursor)))


@router.get("/recurring/upcoming")
def upcoming(request: Request, start: date, end: date, uow: Uow) -> Result[Data]:
    return result(request, uow.read(lambda r: planning.upcoming(r, start, end)))


@router.patch("/recurring/{identifier}", response_model=Result[s.RecurringRead])
def edit_recurring(
    request: Request, identifier: UUID, body: s.RecurringEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"recurring.edit:{identifier}",
        data,
        lambda r: planning.recurring(r, data, str(identifier)),
    )
