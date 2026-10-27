from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool


@event.listens_for(Session, "after_begin")
def workspace_context(db: Session, transaction: object, connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        # Transaction-local and parameterized: no scope survives pooled connection reuse.
        from sqlalchemy import text

        connection.execute(
            text("SELECT set_config('app.workspace_id', :scope, true)"),
            {"scope": db.info.get("workspace_scope", "")},
        )


def postgres_url(raw: str) -> URL:
    try:
        url = make_url(raw)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError
        if not url.host or not url.database or not url.username:
            raise ValueError
        if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError
        return url.set(drivername="postgresql+psycopg")
    except Exception:
        raise ValueError("A PostgreSQL URL with sslmode=require or stricter is required.") from None


def build_engine(raw: str) -> Engine:
    # Neon already pools connections. Do not hold a second pool open across compute suspension.
    engine = create_engine(
        postgres_url(raw),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "prepare_threshold": None},
    )

    @event.listens_for(engine, "begin")
    def transaction_timeout(connection: Connection) -> None:
        # PgBouncer rejects startup options. SET LOCAL applies to this transaction only.
        connection.exec_driver_sql("SET LOCAL statement_timeout = 5000")

    return engine


def database_session(engine: Engine | None) -> Iterator[Session]:
    if engine is None:
        raise HTTPException(503, "Database is not configured.")
    with Session(engine, expire_on_commit=False) as db:
        try:
            yield db
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(503, "Database operation is unavailable.") from None


def session(request: Request) -> Iterator[Session]:
    yield from database_session(request.app.state.engine)


def auth_session(request: Request) -> Iterator[Session]:
    yield from database_session(request.app.state.auth_engine)
