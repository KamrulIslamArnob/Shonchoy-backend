"""Composition of the connected development finance REST routers."""

from fastapi import APIRouter, Depends

from fintrack_core.auth import authenticated_access
from fintrack_core.finance.transport import (
    accounts,
    budgets,
    catalog,
    ledger,
    profile,
    recurring,
    reports,
    rules,
)

router = APIRouter(prefix="/v1/core", dependencies=[Depends(authenticated_access)])
router.include_router(profile.router)
router.include_router(accounts.router)
router.include_router(catalog.router)
router.include_router(ledger.router)
router.include_router(rules.router)
router.include_router(budgets.router)
router.include_router(recurring.router)
router.include_router(reports.router)
