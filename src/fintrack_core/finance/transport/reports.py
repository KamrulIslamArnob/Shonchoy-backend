"""Reports REST contract and use-case mapping."""

from fastapi import APIRouter, Request

from fintrack_common.api import Result
from fintrack_core.finance import schemas as s
from fintrack_core.finance.application import reporting
from fintrack_core.finance.domain import Data
from fintrack_core.finance.http import Uow, result

router = APIRouter(tags=["core reports"])


@router.get("/dashboard/summary", response_model=Result[s.Summary])
@router.get("/reports/spending", response_model=Result[s.Summary])
@router.get("/reports/cashflow", response_model=Result[s.Summary])
@router.get("/reports/net-worth", response_model=Result[s.Summary])
def summary(
    request: Request, selected: str, uow: Uow, currency: s.Currency = "BDT"
) -> Result[Data]:
    return result(request, uow.read(lambda r: reporting.summary(r, selected, currency)))
