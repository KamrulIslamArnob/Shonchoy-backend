"""Opt-in PostgreSQL RLS verification using the restricted runtime role.

Run only on a disposable development branch after applying migrations. All rows
created here use fresh random workspace IDs; cleanup never targets another scope.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from fintrack_core.config import Settings
from fintrack_core.database import build_engine
from fintrack_core.finance import models as m
from fintrack_core.finance.application import accounts
from fintrack_core.finance.persistence import SqlUnitOfWork
from fintrack_core.finance.schemas import AccountCreate


def test_runtime_role_cannot_read_other_workspaces_or_use_missing_context():
    if os.environ.get("FINTRACK_RUN_PRIVATE_RLS_TESTS") != "true":
        pytest.skip("Opt in on a disposable branch with FINTRACK_RUN_PRIVATE_RLS_TESTS=true")
    settings = Settings()
    if not settings.database_url or not settings.command_fingerprint_key:
        pytest.fail("Configure the restricted runtime database and command fingerprint key.")
    engine = build_engine(settings.database_url.get_secret_value())
    owners = [uuid4(), uuid4()]
    secret = settings.command_fingerprint_key.get_secret_value()
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
            assert not any(role), "The runtime role must not bypass row-level security."
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_tables WHERE tablename LIKE 'core_%' "
                        "AND tableowner = current_user"
                    )
                ).scalar_one()
                == 0
            ), "Use a runtime role that does not own finance tables."
        for owner in owners:
            with Session(engine) as db:
                uow = SqlUnitOfWork(db, secret, owner)
                payload = AccountCreate(name="Synthetic RLS cash").model_dump(mode="json")
                uow.command(
                    str(uuid4()),
                    "accounts.create",
                    payload,
                    lambda r, payload=payload: accounts.create(r, payload),
                )
        for owner in owners:
            with Session(engine) as db:
                db.info["workspace_scope"] = str(owner)
                rows = list(
                    db.scalars(select(m.Account))
                )  # Deliberately omit an application filter.
                assert len(rows) == 1 and rows[0].scope_id == owner
                assert list(db.scalars(select(m.Workspace.id))) == [owner]
        with Session(engine) as db:
            assert list(db.scalars(select(m.Account))) == []
            assert list(db.scalars(select(m.Workspace))) == []
    finally:
        try:
            for owner in owners:
                with Session(engine) as db, db.begin():
                    db.info["workspace_scope"] = str(owner)
                    for model in (m.Outbox, m.Audit, m.Idempotency, m.Observation, m.Account):
                        db.execute(delete(model).where(model.scope_id == owner))
                    db.execute(delete(m.Workspace).where(m.Workspace.id == owner))
        finally:
            engine.dispose()
