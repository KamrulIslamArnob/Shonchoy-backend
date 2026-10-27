from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fintrack_common.api import Page, Result, envelope, require_dev_key
from fintrack_core.database import session
from fintrack_core.models import Account, Transaction
from fintrack_core.schemas import AccountCreate, AccountRead, TransactionCreate, TransactionRead

bearer = HTTPBearer(auto_error=False)


def dev_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if not request.app.state.settings.enable_development_routes:
        raise HTTPException(404, "Resource not found.")
    require_dev_key(
        request.app.state.settings.dev_api_key, credentials.credentials if credentials else None
    )


router = APIRouter(prefix="/v1", dependencies=[Depends(dev_access)])
DB = Annotated[Session, Depends(session)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/health/ready", tags=["health"])
def ready(db: DB) -> dict[str, str]:
    db.execute(text("SELECT 1 FROM dev_accounts LIMIT 0"))
    db.execute(text("SELECT 1 FROM dev_transactions LIMIT 0"))
    return {"status": "ready"}


@router.post("/accounts", response_model=Result[AccountRead], status_code=201, tags=["accounts"])
def create_account(request: Request, body: AccountCreate, db: DB) -> Result[AccountRead]:
    account = Account(**body.model_dump())
    db.add(account)
    db.commit()
    return envelope(request, AccountRead.model_validate(account))


@router.get("/accounts", response_model=Result[Page[AccountRead]], tags=["accounts"])
def accounts(
    request: Request, db: DB, limit: Limit = 50, cursor: UUID | None = None
) -> Result[Page[AccountRead]]:
    query = select(Account).order_by(Account.id).limit(limit + 1)
    if cursor:
        query = query.where(Account.id > cursor)
    rows = list(db.scalars(query))
    return envelope(
        request,
        Page(
            items=[AccountRead.model_validate(a) for a in rows[:limit]],
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
        ),
    )


@router.get("/accounts/{account_id}", response_model=Result[AccountRead], tags=["accounts"])
def account(request: Request, account_id: UUID, db: DB) -> Result[AccountRead]:
    row = db.get(Account, account_id)
    if row is None:
        raise HTTPException(404, "Account not found.")
    return envelope(request, AccountRead.model_validate(row))


@router.post(
    "/transactions", response_model=Result[TransactionRead], status_code=201, tags=["transactions"]
)
def create_transaction(
    request: Request, body: TransactionCreate, db: DB
) -> Result[TransactionRead]:
    if db.get(Account, body.account_id) is None:
        raise HTTPException(404, "Account not found.")
    transaction = Transaction(**body.model_dump())
    db.add(transaction)
    db.commit()
    return envelope(request, TransactionRead.model_validate(transaction))


@router.get("/transactions", response_model=Result[Page[TransactionRead]], tags=["transactions"])
def transactions(
    request: Request,
    db: DB,
    limit: Limit = 50,
    cursor: UUID | None = None,
    account_id: Annotated[UUID | None, Query(alias="accountId")] = None,
) -> Result[Page[TransactionRead]]:
    query = select(Transaction).order_by(Transaction.id).limit(limit + 1)
    if cursor:
        query = query.where(Transaction.id > cursor)
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    rows = list(db.scalars(query))
    return envelope(
        request,
        Page(
            items=[TransactionRead.model_validate(t) for t in rows[:limit]],
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
        ),
    )


@router.get(
    "/transactions/{transaction_id}", response_model=Result[TransactionRead], tags=["transactions"]
)
def transaction(request: Request, transaction_id: UUID, db: DB) -> Result[TransactionRead]:
    row = db.get(Transaction, transaction_id)
    if row is None:
        raise HTTPException(404, "Transaction not found.")
    return envelope(request, TransactionRead.model_validate(row))
