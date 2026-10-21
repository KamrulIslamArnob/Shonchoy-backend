"""Accounts REST contract and use-case mapping."""

from uuid import UUID

from fastapi import APIRouter, Request

from fintrack_common.api import Page, Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import accounts
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Limit, Uow, collection, command, result
from fintrack_core.finance.ports import ReadRepositories

router = APIRouter(tags=["core accounts"])


@router.post("/accounts", response_model=Result[s.AccountRead], status_code=201)
def create_account(request: Request, body: s.AccountCreate, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(request, uow, key, "accounts.create", data, lambda r: accounts.create(r, data))


@router.post("/accounts/batches", status_code=201)
def account_batch(request: Request, body: s.AccountBatch, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(request, uow, key, "accounts.batch", data, lambda r: accounts.batch(r, data))


@router.get("/accounts", response_model=Result[Page[s.AccountRead]])
def account_list(
    request: Request, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    return result(request, uow.read(lambda r: collection(r.accounts, limit, cursor)))


@router.get("/accounts/{identifier}", response_model=Result[s.AccountRead])
def get_account(request: Request, identifier: UUID, uow: Uow) -> Result[Data]:
    return result(request, uow.read(lambda r: r.accounts.get(str(identifier))))


@router.patch("/accounts/{identifier}", response_model=Result[s.AccountRead])
def edit_account(
    request: Request, identifier: UUID, body: s.AccountEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"accounts.edit:{identifier}",
        data,
        lambda r: accounts.edit(r, str(identifier), data),
    )


@router.post("/accounts/{identifier}/archive", response_model=Result[s.AccountRead])
def archive_account(
    request: Request, identifier: UUID, body: s.Expected, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"accounts.archive:{identifier}",
        data,
        lambda r: accounts.lifecycle(r, str(identifier), data, True),
    )


@router.post("/accounts/{identifier}/restore", response_model=Result[s.AccountRead])
def restore_account(
    request: Request, identifier: UUID, body: s.Expected, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"accounts.restore:{identifier}",
        data,
        lambda r: accounts.lifecycle(r, str(identifier), data, False),
    )


@router.post(
    "/accounts/{identifier}/balance-observations",
    response_model=Result[s.ObservationResult],
    status_code=201,
)
def observe(
    request: Request, identifier: UUID, body: s.ObservationCreate, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        f"accounts.observe:{identifier}",
        data,
        lambda r: accounts.observe(r, str(identifier), data),
    )


@router.get(
    "/accounts/{identifier}/balance-observations", response_model=Result[Page[s.ObservationRead]]
)
def observations(
    request: Request, identifier: UUID, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    def read(r: ReadRepositories) -> Data:
        r.accounts.get(str(identifier))
        return collection(r.observations, limit, cursor, {"account_id": str(identifier)})

    return result(request, uow.read(read))
