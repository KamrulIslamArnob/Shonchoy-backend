"""Scoped SQL adapters and atomic command unit of work."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, Date, Uuid, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m
from fintrack_core.finance.domain import Data, DomainError, require
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


class SqlUnitOfWork:
    def __init__(self, db: Session, fingerprint_key: str, scope: UUID = DEV_SCOPE) -> None:
        self.db, self.scope = db, scope
        self.fingerprint_key = fingerprint_key.encode()
        self.repositories = Repositories(
            *[
                SqlRepository(db, model, scope)
                for model in (
                    m.Account,
                    m.Observation,
                    m.Category,
                    m.Group,
                    m.Transaction,
                    m.Rule,
                    m.Budget,
                    m.Recurring,
                    m.Workspace,
                )
            ]
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
