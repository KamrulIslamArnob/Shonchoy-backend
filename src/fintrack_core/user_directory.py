"""Read-only lookup against the managed identity store."""

import re

from sqlalchemy import Boolean, Column, MetaData, String, Table, cast, func, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from fintrack_core.finance.domain import Data

managed_users = Table(
    "user",
    MetaData(),
    Column("id", String),
    Column("name", String),
    Column("email", String),
    Column("emailVerified", Boolean),
    schema="neon_auth",
)


def search_predicate(query: str) -> ColumnElement[bool]:
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", query):
        return func.lower(managed_users.c.email) == func.lower(literal(query))
    # Both the stored field and input use PostgreSQL's lower(), and literal
    # wildcard characters stay literal. This exactly matches the index expressions.
    escaped = query.replace("/", "//").replace("%", "/%").replace("_", "/_")
    term = func.lower(literal(escaped))
    pattern = term.concat("%") if len(query) == 2 else literal("%").concat(term).concat("%")
    return or_(
        func.lower(managed_users.c.name).like(pattern, escape="/"),
        func.lower(managed_users.c.email).like(pattern, escape="/"),
    )


def search_users(
    auth_db: Session, subject: str, query: str, test_user_ids: list[str] | None = None
) -> Data:
    query = query.strip()
    if len(query) < 2:
        return {"items": []}
    verified_or_test: ColumnElement[bool] = managed_users.c.emailVerified.is_(True)
    if test_user_ids:
        # Only explicitly selected fixture IDs in the reserved test domain bypass
        # verification. This does not alter their actual email verification state.
        verified_or_test = or_(
            verified_or_test,
            (cast(managed_users.c.id, String).in_(test_user_ids))
            & managed_users.c.email.like("%@seed.shonchoy.test"),
        )
    with auth_db.begin():
        rows = auth_db.execute(
            select(managed_users.c.id, managed_users.c.name, managed_users.c.email)
            .where(
                verified_or_test,
                cast(managed_users.c.id, String) != subject,
                search_predicate(query),
            )
            .order_by(managed_users.c.name, managed_users.c.id)
            .limit(20)
        ).all()
    return {"items": [{"id": str(row.id), "name": row.name, "email": row.email} for row in rows]}
