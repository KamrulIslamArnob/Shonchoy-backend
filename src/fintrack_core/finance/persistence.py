"""Scoped SQL adapters and atomic command unit of work."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, Date, Uuid, case, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m
from fintrack_core.finance.domain import (
    MAX_MINOR,
    Data,
    DomainError,
    require,
    shift_month,
)
from fintrack_core.finance.ports import ReadRepositories, Repositories

# Fixed server-owned development scope; never accepted from a request or identity claim.
DEV_SCOPE = UUID("00000000-0000-4000-8000-000000000061")


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()
    if isinstance(value, date | UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_value(v) for v in value]
    return value


class SqlRepository:
    """Internal mapping helper, composed as separate resource repositories, not an HTTP CRUD API."""

    def __init__(self, db: Session, model: type[m.Row] | type[m.Workspace], scope: UUID) -> None:
        self.db, self.model, self.scope = db, model, scope

    def _scope(self) -> Any:
        return (
            self.model.id == self.scope
            if self.model is m.Workspace
            else self.model.__table__.c.scope_id == self.scope
        )

    def _data(self, row: Any) -> Data:
        return {
            column.key: json_value(getattr(row, column.key))
            for column in inspect(row).mapper.column_attrs
            if column.key != "scope_id"
        }

    def _values(self, data: Data) -> Data:
        values = dict(data)
        for name, value in values.items():
            column = self.model.__table__.columns[name]
            if value is not None and isinstance(column.type, Uuid) and isinstance(value, str):
                values[name] = UUID(value)
            elif value is not None and isinstance(column.type, Date) and isinstance(value, str):
                values[name] = date.fromisoformat(value)
        return values

    def get(self, identifier: str) -> Data:
        row = self.db.scalar(
            select(self.model).where(self._scope(), self.model.id == UUID(identifier))
        )
        if row is None:
            raise DomainError(404, "Resource not found.")
        return self._data(row)

    def list(
        self, *, limit: int = 100, cursor: str | None = None, filters: Data | None = None
    ) -> list[Data]:
        query = select(self.model).where(self._scope()).order_by(self.model.id).limit(limit)
        if cursor:
            query = query.where(self.model.id > UUID(cursor))
        for key, value in (filters or {}).items():
            if key == "booked_from":
                query = query.where(m.Transaction.booked_on >= date.fromisoformat(value))
            elif key == "booked_to":
                query = query.where(m.Transaction.booked_on <= date.fromisoformat(value))
            else:
                column = self.model.__table__.columns[key]
                converted = (
                    UUID(value)
                    if isinstance(column.type, Uuid) and isinstance(value, str)
                    else value
                )
                query = query.where(column == converted)
        return [self._data(row) for row in self.db.scalars(query)]

    def add(self, values: Data) -> Data:
        data = self._values(values)
        if self.model is not m.Workspace:
            data["scope_id"] = self.scope
        row = self.model(**data)
        self.db.add(row)
        self.db.flush()
        return self._data(row)

    def save(self, identifier: str, version: int, changes: Data) -> Data:
        values = self._values(changes)
        values["version"] = version + 1
        if self.model is not m.Workspace:
            values["updated_at"] = datetime.now(UTC)
        result = self.db.execute(
            update(self.model)
            .where(
                self._scope(),
                self.model.id == UUID(identifier),
                self.model.version == version,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            self.get(identifier)
            raise DomainError(409, "Resource changed. Reload and retry with its current version.")
        self.db.expire_all()
        return self.get(identifier)


class SqlLedger:
    """Analytical ledger queries and cashflow summaries."""

    def __init__(self, db: Session, scope: UUID) -> None:
        self.db = db
        self.scope = scope

    def visible_transactions(self, start: str, end: str, currency: str) -> list[Data]:
        query = (
            select(m.Transaction)
            .join(
                m.Account,
                (m.Transaction.account_id == m.Account.id)
                & (m.Transaction.scope_id == m.Account.scope_id),
            )
            .where(
                m.Transaction.scope_id == self.scope,
                m.Transaction.currency == currency,
                m.Account.hidden.is_(False),
                m.Transaction.booked_on >= date.fromisoformat(start),
                m.Transaction.booked_on <= date.fromisoformat(end),
            )
            .order_by(m.Transaction.id)
            .limit(10001)
        )
        rows = list(self.db.scalars(query))
        require(len(rows) <= 10000, "Transaction report limit exceeded.")
        repo = SqlRepository(self.db, m.Transaction, self.scope)
        return [repo._data(row) for row in rows]

    def cashflow(self, month: str, currency: str) -> Data:
        start_date = date.fromisoformat(f"{month}-01")
        next_month = shift_month(month, 1)
        end_date = date.fromisoformat(f"{next_month}-01")

        query = (
            select(m.Transaction)
            .join(
                m.Account,
                (m.Transaction.account_id == m.Account.id)
                & (m.Transaction.scope_id == m.Account.scope_id),
            )
            .where(
                m.Transaction.scope_id == self.scope,
                m.Transaction.currency == currency,
                m.Account.hidden.is_(False),
                m.Transaction.booked_on >= start_date,
                m.Transaction.booked_on < end_date,
                m.Transaction.hidden.is_(False),
                m.Transaction.deleted.is_(False),
                m.Transaction.pending.is_(False),
            )
            .limit(10001)
        )
        rows = list(self.db.scalars(query))
        require(len(rows) <= 10000, "Transaction report limit exceeded.")

        income = expense = 0
        categories: dict[str, int] = {}
        for item in rows:
            if item.kind == "income":
                income += item.amount_minor * (1 if item.direction == "in" else -1)
            elif item.kind == "expense":
                sign = 1 if item.direction == "out" else -1
                if item.splits:
                    for part in item.splits:
                        amt = sign * int(part["amount_minor"])
                        expense += amt
                        cat_key = (
                            str(part.get("category_id"))
                            if part.get("category_id")
                            else "uncategorized"
                        )
                        categories[cat_key] = categories.get(cat_key, 0) + amt
                else:
                    amt = sign * item.amount_minor
                    expense += amt
                    cat_key = str(item.category_id) if item.category_id else "uncategorized"
                    categories[cat_key] = categories.get(cat_key, 0) + amt

        agg_values = [income, expense, income - expense, *categories.values()]
        require(
            all(abs(v) <= MAX_MINOR for v in agg_values),
            "Aggregated amount exceeds the supported JSON integer range.",
        )
        return {
            "income_minor": income,
            "expense_minor": expense,
            "net_minor": income - expense,
            "by_category": categories,
        }

    def balances(self, currency: str) -> Data:
        stmt = select(
            func.coalesce(
                func.sum(case((m.Account.is_asset.is_(True), m.Account.balance_minor), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((m.Account.is_asset.is_(False), m.Account.balance_minor), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            m.Account.kind.in_(("cash", "checking", "savings", "mfs")),
                            m.Account.balance_minor,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((m.Account.kind == "dps", m.Account.balance_minor), else_=0)), 0
            ),
        ).where(
            m.Account.scope_id == self.scope,
            m.Account.currency == currency,
            m.Account.hidden.is_(False),
            m.Account.archived.is_(False),
        )
        row = self.db.execute(stmt).one()
        assets, debt, spendable, committed = int(row[0]), int(row[1]), int(row[2]), int(row[3])
        require(
            all(
                abs(v) <= MAX_MINOR
                for v in [
                    assets,
                    debt,
                    spendable,
                    committed,
                    assets - debt,
                    spendable + committed - debt,
                ]
            ),
            "Aggregate balance exceeds JSON integer range.",
        )
        return {
            "assets_minor": assets,
            "liabilities_minor": debt,
            "net_worth_minor": assets - debt,
            "spendable_minor": spendable,
            "committed_minor": committed,
            "liquid_net_minor": spendable + committed - debt,
        }

    def summary(self, month: str, currency: str) -> Data:
        cashflow = self.cashflow(month, currency)
        bal = self.balances(currency)
        return {
            "month": month,
            "currency": currency,
            "policy_version": "dev-v1",
            "cashflow": cashflow,
            "assets_minor": bal["assets_minor"],
            "liabilities_minor": bal["liabilities_minor"],
            "net_worth_minor": bal["net_worth_minor"],
            "spendable_minor": bal["spendable_minor"],
            "committed_minor": bal["committed_minor"],
            "liquid_net_minor": bal["liquid_net_minor"],
            "computed_on": date.today().isoformat(),
            "balance_history_available": False,
            "balance_basis": "observations; transaction edits do not alter observed balances",
        }


class SqlUnitOfWork:
    def __init__(self, db: Session, fingerprint_key: str, scope: UUID = DEV_SCOPE) -> None:
        self.db, self.scope = db, scope
        db.info["workspace_scope"] = str(scope)
        self.fingerprint_key = fingerprint_key.encode()
        self.repositories = Repositories(
            accounts=SqlRepository(db, m.Account, scope),
            observations=SqlRepository(db, m.Observation, scope),
            categories=SqlRepository(db, m.Category, scope),
            groups=SqlRepository(db, m.Group, scope),
            transactions=SqlRepository(db, m.Transaction, scope),
            rules=SqlRepository(db, m.Rule, scope),
            budgets=SqlRepository(db, m.Budget, scope),
            recurring=SqlRepository(db, m.Recurring, scope),
            profile=SqlRepository(db, m.Workspace, scope),
            ledger=SqlLedger(db, scope),
        )

    def ready(self) -> Data:
        def probe(_: ReadRepositories) -> Data:
            for table in m.Workspace.metadata.sorted_tables:
                if table.name.startswith("core_"):
                    self.db.execute(select(table).limit(0))
            return {"status": "ready", "mode": "development"}

        return self.read(probe)

    def _lock_workspace(self) -> None:
        dialect = self.db.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        self.db.execute(insert(m.Workspace).values(id=self.scope).on_conflict_do_nothing())
        if dialect == "postgresql":
            self.db.execute(text("SET LOCAL lock_timeout = 2500"))
        self.db.scalar(select(m.Workspace).where(m.Workspace.id == self.scope).with_for_update())

    def command(
        self, key: str, operation: str, payload: Data, action: Callable[[Repositories], Data]
    ) -> Data:
        require(8 <= len(key) <= 128 and key.isascii(), "Invalid idempotency key.")
        encoded = json.dumps(json_value(payload), sort_keys=True, separators=(",", ":")).encode()
        fingerprint = hmac.new(
            self.fingerprint_key, b"finance-command-v1:" + encoded, hashlib.sha256
        ).hexdigest()
        with self.db.begin():
            self._lock_workspace()
            existing = self.db.get(m.Idempotency, (self.scope, key))
            if existing:
                require(
                    existing.operation == operation
                    and hmac.compare_digest(existing.fingerprint, fingerprint),
                    "Idempotency key was already used for a different command.",
                    409,
                )
                return dict(existing.result)
            result = cast(Data, json_value(action(self.repositories)))
            audit_id = uuid4()
            self.db.add(
                m.Audit(id=audit_id, scope_id=self.scope, operation=operation, command_key=key)
            )
            self.db.flush()
            self.db.add(m.Outbox(scope_id=self.scope, event_id=audit_id, event_type=operation))
            self.db.add(
                m.Idempotency(
                    scope_id=self.scope,
                    key=key,
                    operation=operation,
                    fingerprint=fingerprint,
                    result=result,
                )
            )
            self.db.flush()
            return result

    def read(self, action: Callable[[ReadRepositories], Data]) -> Data:
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        try:
            return action(self.repositories)
        finally:
            self.db.rollback()
