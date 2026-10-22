from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "dev_accounts"
    __table_args__ = (CheckConstraint("length(currency) = 3", name="account_currency_length"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Transaction(Base):
    __tablename__ = "dev_transactions"
    __table_args__ = (
        CheckConstraint("amount_minor != 0", name="transaction_nonzero"),
        CheckConstraint(
            "amount_minor BETWEEN -9000000000000000 AND 9000000000000000",
            name="transaction_amount_range",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("dev_accounts.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(240))
    booked_on: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
