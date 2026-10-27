"""Persistence models for disposable, workspace-scoped development data."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fintrack_core.models import Base


class Workspace(Base):
    __tablename__ = "core_workspaces"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str] = mapped_column(String(120), default="Development user")
    currency: Mapped[str] = mapped_column(String(3), default="BDT")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Dhaka")
    onboarded: Mapped[bool] = mapped_column(default=False)
    goals: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AppUser(Base):
    __tablename__ = "core_users"
    __table_args__ = (UniqueConstraint("auth_issuer", "auth_subject"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    auth_issuer: Mapped[str] = mapped_column(String(500))
    auth_subject: Mapped[str] = mapped_column(String(255))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("core_workspaces.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Row(Base):
    __abstract__ = True
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_id: Mapped[UUID] = mapped_column(ForeignKey("core_workspaces.id"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Account(Row):
    __tablename__ = "core_accounts"
    __table_args__ = (
        UniqueConstraint("id", "scope_id"),
        CheckConstraint("balance_minor BETWEEN 0 AND 9000000000000000"),
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    institution: Mapped[str] = mapped_column(String(120), default="Manual")
    is_asset: Mapped[bool] = mapped_column(default=True)
    balance_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    hidden: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    debit_card_last4: Mapped[str | None] = mapped_column(String(4), default=None)


class Observation(Row):
    __tablename__ = "core_balance_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "scope_id"], ["core_accounts.id", "core_accounts.scope_id"]
        ),
    )
    account_id: Mapped[UUID]
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    effective_on: Mapped[date]


class Group(Row):
    __tablename__ = "core_category_groups"
    __table_args__ = (UniqueConstraint("id", "scope_id"),)
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(7), default="#718096")
    archived: Mapped[bool] = mapped_column(default=False)


class Category(Row):
    __tablename__ = "core_categories"
    __table_args__ = (
        UniqueConstraint("id", "scope_id"),
        ForeignKeyConstraint(
            ["group_id", "scope_id"], ["core_category_groups.id", "core_category_groups.scope_id"]
        ),
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("core_category_groups.id"))
    color: Mapped[str] = mapped_column(String(7), default="#718096")
    icon: Mapped[str] = mapped_column(String(40), default="tag")
    archived: Mapped[bool] = mapped_column(default=False)


class Transaction(Row):
    __tablename__ = "core_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "scope_id"], ["core_categories.id", "core_categories.scope_id"]
        ),
        ForeignKeyConstraint(
            ["account_id", "scope_id"], ["core_accounts.id", "core_accounts.scope_id"]
        ),
        CheckConstraint("amount_minor BETWEEN 1 AND 9000000000000000"),
        CheckConstraint("kind IN ('income','expense','transfer')"),
        CheckConstraint("direction IN ('in','out')"),
    )
    account_id: Mapped[UUID] = mapped_column(index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(3))
    merchant: Mapped[str] = mapped_column(String(240))
    booked_on: Mapped[date] = mapped_column(index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("core_categories.id"))
    reviewed: Mapped[bool] = mapped_column(default=False)
    pending: Mapped[bool] = mapped_column(default=False)
    hidden: Mapped[bool] = mapped_column(default=False)
    deleted: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str] = mapped_column(String(2000), default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    splits: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    transfer_pair_id: Mapped[UUID | None]
    classification_source: Mapped[str] = mapped_column(String(16), default="manual")


class Rule(Row):
    __tablename__ = "core_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "scope_id"], ["core_accounts.id", "core_accounts.scope_id"]
        ),
        ForeignKeyConstraint(
            ["set_category_id", "scope_id"], ["core_categories.id", "core_categories.scope_id"]
        ),
    )
    merchant_contains: Mapped[str | None] = mapped_column(String(120))
    min_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("core_accounts.id"))
    set_category_id: Mapped[UUID | None] = mapped_column(ForeignKey("core_categories.id"))
    set_merchant: Mapped[str | None] = mapped_column(String(240))
    add_tag: Mapped[str | None] = mapped_column(String(40))
    archived: Mapped[bool] = mapped_column(default=False)


class Budget(Row):
    __tablename__ = "core_budgets"
    __table_args__ = (UniqueConstraint("scope_id", "currency"),)
    currency: Mapped[str] = mapped_column(String(3))
    income_minor: Mapped[int] = mapped_column(BigInteger)
    savings_minor: Mapped[int] = mapped_column(BigInteger)
    versions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    overrides: Mapped[dict[str, dict[str, int]]] = mapped_column(JSON, default=dict)
    rollover: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(default=False)


class Recurring(Row):
    __tablename__ = "core_recurring"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "scope_id"], ["core_accounts.id", "core_accounts.scope_id"]
        ),
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("core_accounts.id"))
    name: Mapped[str] = mapped_column(String(240))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    direction: Mapped[str] = mapped_column(String(3))
    frequency: Mapped[str] = mapped_column(String(16))
    next_on: Mapped[date]
    end_on: Mapped[date | None]
    stopped: Mapped[bool] = mapped_column(default=False)


class Idempotency(Base):
    __tablename__ = "core_idempotency"
    scope_id: Mapped[UUID] = mapped_column(ForeignKey("core_workspaces.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class Audit(Row):
    __tablename__ = "core_audit_events"
    __table_args__ = (UniqueConstraint("id", "scope_id"),)
    operation: Mapped[str] = mapped_column(String(160))
    command_key: Mapped[str] = mapped_column(String(128))


class Outbox(Row):
    __tablename__ = "core_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "scope_id"], ["core_audit_events.id", "core_audit_events.scope_id"]
        ),
    )
    event_id: Mapped[UUID] = mapped_column(ForeignKey("core_audit_events.id"), unique=True)
    event_type: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="pending")
