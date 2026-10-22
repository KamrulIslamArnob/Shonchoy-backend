"""Ledger REST contract and use-case mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from fintrack_common.api import Page, Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import transactions
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Limit, Uow, collection, command, result

router = APIRouter(tags=["core ledger"])


@router.post("/transactions", response_model=Result[s.TransactionRead], status_code=201)
def create_transaction(
    request: Request, body: s.TransactionCreate, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request, uow, key, "transactions.create", data, lambda r: transactions.create(r, data)
    )


@router.get("/transactions", response_model=Result[Page[s.TransactionRead]])
def transaction_list(
    request: Request,
    uow: Uow,
    limit: Limit = 50,
    cursor: UUID | None = None,
    account_id: Annotated[UUID | None, Query(alias="accountId")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> Result[Data]:
    filters: Data = {} if include_deleted else {"deleted": False}
    if account_id:
        filters["account_id"] = str(account_id)
    return result(request, uow.read(lambda r: collection(r.transactions, limit, cursor, filters)))


@router.get("/transactions/{identifier}", response_model=Result[s.TransactionRead])
def get_transaction(request: Request, identifier: UUID, uow: Uow) -> Result[Data]:
    return result(request, uow.read(lambda r: r.transactions.get(str(identifier))))


@router.patch("/transactions/{identifier}", response_model=Result[s.TransactionRead])
def edit_transaction(
    request: Request, identifier: UUID, body: s.TransactionEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"transactions.edit:{identifier}",
        data,
        lambda r: transactions.edit(r, str(identifier), data),
    )


@router.put("/transactions/{identifier}/splits", response_model=Result[s.TransactionRead])
def split_transaction(
    request: Request, identifier: UUID, body: s.Splits, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        f"transactions.split:{identifier}",
        data,
        lambda r: transactions.splits(r, str(identifier), data),
    )


@router.post("/transactions/{identifier}/review", response_model=Result[s.TransactionRead])
def review(request: Request, identifier: UUID, body: s.Review, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"transactions.review:{identifier}",
        data,
        lambda r: transactions.flags(r, str(identifier), data, {"reviewed": body.reviewed}),
    )


@router.post("/transactions/{identifier}/visibility", response_model=Result[s.TransactionRead])
def visibility(
    request: Request, identifier: UUID, body: s.Visibility, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"transactions.visibility:{identifier}",
        data,
        lambda r: transactions.flags(r, str(identifier), data, {"hidden": body.hidden}),
    )


@router.post("/transactions/{identifier}/delete", response_model=Result[s.TransactionRead])
def delete_transaction(
    request: Request, identifier: UUID, body: s.Lifecycle, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"transactions.delete:{identifier}",
        data,
        lambda r: transactions.flags(r, str(identifier), data, {"deleted": True}),
    )


@router.post("/transactions/{identifier}/restore", response_model=Result[s.TransactionRead])
def restore_transaction(
    request: Request, identifier: UUID, body: s.Lifecycle, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump()
    return command(
        request,
        uow,
        key,
        f"transactions.restore:{identifier}",
        data,
        lambda r: transactions.flags(r, str(identifier), data, {"deleted": False}),
    )


@router.post("/transaction-reviews")
def review_batch(request: Request, body: s.ReviewBatch, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        "transactions.review-batch",
        data,
        lambda r: transactions.review_batch(r, data),
    )


@router.post("/transfers", status_code=201)
def transfer(request: Request, body: s.Transfer, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request, uow, key, "transfers.create", data, lambda r: transactions.transfer(r, data)
    )
