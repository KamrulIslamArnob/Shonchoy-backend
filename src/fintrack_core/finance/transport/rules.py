"""Rules REST contract and use-case mapping."""

from uuid import UUID

from fastapi import APIRouter, Request

from fintrack_common.api import Page, Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import catalog, transactions
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Limit, Uow, collection, command, result

router = APIRouter(tags=["core rules"])


@router.post("/rules", response_model=Result[s.RuleRead], status_code=201)
def create_rule(request: Request, body: s.RuleCreate, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(request, uow, key, "rules.create", data, lambda r: catalog.rule(r, data))


@router.get("/rules", response_model=Result[Page[s.RuleRead]])
def rule_list(
    request: Request, uow: Uow, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Data]:
    return result(request, uow.read(lambda r: collection(r.rules, limit, cursor)))


@router.patch("/rules/{identifier}", response_model=Result[s.RuleRead])
def edit_rule(
    request: Request, identifier: UUID, body: s.RuleEdit, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    return command(
        request,
        uow,
        key,
        f"rules.edit:{identifier}",
        data,
        lambda r: catalog.rule(r, data, str(identifier)),
    )


@router.get("/rules/{identifier}/preview")
def preview_rule(request: Request, identifier: UUID, uow: Uow) -> Result[Data]:
    return result(request, uow.read(lambda r: transactions.preview_rule(r, str(identifier))))


@router.post("/rules/{identifier}/applications")
def apply_rule(
    request: Request, identifier: UUID, body: s.RuleApply, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        f"rules.apply:{identifier}",
        data,
        lambda r: transactions.apply_rule(r, str(identifier), data),
    )
