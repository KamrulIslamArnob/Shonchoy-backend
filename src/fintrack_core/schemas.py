from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from fintrack_common.api import DTO

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class AccountCreate(DTO):
    name: Name
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "BDT"

    @field_validator("currency")
    @classmethod
    def supported_currency(cls, value: str) -> str:
        if value not in {"BDT", "USD", "EUR", "GBP"}:
            raise ValueError("Unsupported development currency")
        return value


class AccountRead(AccountCreate):
    id: UUID
    created_at: datetime


class TransactionCreate(DTO):
    account_id: UUID
    amount_minor: Annotated[
        int, Field(strict=True, ge=-9_000_000_000_000_000, le=9_000_000_000_000_000)
    ]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
    ]
    booked_on: date

    @field_validator("amount_minor")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Amount must be nonzero")
        return value


class TransactionRead(TransactionCreate):
    id: UUID
    created_at: datetime
