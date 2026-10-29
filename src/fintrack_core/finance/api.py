"""Composition of the connected development finance REST routers."""

from fastapi import APIRouter, Depends

from fintrack_core.auth import authenticated_access, authenticated_identity
from fintrack_core.finance.transport import (
    accounts,
    advisor,
    budgets,
    catalog,
    ledger,
    profile,
    recurring,
    reports,
    rules,
    user_directory,
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
directory_router = APIRouter(prefix="/v1/core", dependencies=[Depends(authenticated_identity)])
directory_router.include_router(user_directory.router)
directory_router.include_router(advisor.router)
