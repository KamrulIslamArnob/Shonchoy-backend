"""Budgets REST contract and use-case mapping."""

from fastapi import APIRouter, Request

from fintrack_common.api import Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import planning
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Key, Uow, command, result

router = APIRouter(tags=["core budgets"])


@router.put("/budgets/{selected}", response_model=Result[s.BudgetRead], status_code=201)
def create_budget(
    request: Request, selected: str, body: s.BudgetCreate, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        f"budgets.create:{selected}",
        data,
        lambda r: planning.create_budget(r, selected, data),
    )


@router.get("/budgets/{selected}", response_model=Result[s.BudgetView])
def get_budget(
    request: Request, selected: str, uow: Uow, currency: s.Currency = "BDT"
) -> Result[Data]:
    return result(request, uow.read(lambda r: planning.budget_view(r, selected, currency)))


@router.post("/budgets/{selected}/lines", response_model=Result[s.BudgetRead])
def budget_line(
    request: Request, selected: str, body: s.BudgetLine, uow: Uow, key: Key
) -> Result[Data]:
    data = body.model_dump(mode="json")
    return command(
        request,
        uow,
        key,
        f"budgets.line:{selected}",
        data,
        lambda r: planning.line(r, selected, data),
    )


@router.patch("/budgets", response_model=Result[s.BudgetRead])
def budget_settings(request: Request, body: s.BudgetEdit, uow: Uow, key: Key) -> Result[Data]:
    data = body.model_dump(mode="json", exclude_unset=True)
    data.setdefault("currency", body.currency)
    return command(
        request, uow, key, "budgets.settings", data, lambda r: planning.budget_settings(r, data)
    )
