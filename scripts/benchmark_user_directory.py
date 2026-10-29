"""Benchmark synthetic search on a specifically named disposable local PostgreSQL DB."""

import ipaddress
import os
import socket
import statistics
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

PREFIX = "shonchoy_search_benchmark_"


def local_target(raw: str):
    """Fail closed before connecting: no remote host, socket, or ordinary database."""
    url = make_url(raw)
    if (
        url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
        or not url.host
        or not url.database
        or not url.database.startswith(PREFIX)
        or len(url.database) <= len(PREFIX)
    ):
        raise ValueError("A disposable local PostgreSQL benchmark database is required.")
    addresses = socket.getaddrinfo(url.host, url.port or 5432, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
        raise ValueError("The benchmark must connect only to a loopback PostgreSQL server.")
    return url.set(drivername="postgresql+psycopg")


def main() -> None:
    raw = os.environ.get("FINTRACK_SEARCH_BENCHMARK_URL", "")
    if not raw:
        raise SystemExit("Set FINTRACK_SEARCH_BENCHMARK_URL to a disposable local database.")
    engine = create_engine(
        local_target(raw),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"prepare_threshold": None},
    )
    try:
        with engine.begin() as db:
            database, host = db.execute(text("SELECT current_database(), inet_server_addr()")).one()
            if (
                database != engine.url.database
                or host is None
                or not ipaddress.ip_address(host).is_loopback
            ):
                raise ValueError("The server is not the required disposable local database.")
            db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            db.execute(
                text(
                    "CREATE TEMP TABLE directory_bench (id integer, name text, email text, "
                    '"emailVerified" boolean) ON COMMIT PRESERVE ROWS'
                )
            )
            db.execute(
                text("""
                INSERT INTO directory_bench
                SELECT n,
                    CASE WHEN n % 20 = 0 THEN 'বাংলা রহমান ' || n
                         WHEN n % 10 = 0 THEN 'Nadia Rahman ' || n
                         ELSE 'User ' || md5(n::text) END,
                    'person' || n || '@example.test', true
                FROM generate_series(1, 100000) AS n
            """)
            )
            for column in ("name", "email"):
                # Column names are constants, not input from the environment.
                db.execute(
                    text(
                        f"CREATE INDEX ON directory_bench (lower({column}) text_pattern_ops) "
                        'WHERE "emailVerified" IS TRUE'
                    )
                )
                db.execute(
                    text(
                        f"CREATE INDEX ON directory_bench USING gin (lower({column}) gin_trgm_ops) "
                        'WHERE "emailVerified" IS TRUE'
                    )
                )
            db.execute(text("ANALYZE directory_bench"))
            for query in ("na", "nad", "12345", "person12345@example.test", "বাংলা", "zzzzzz"):
                exact_email = "@" in query
                pattern = (
                    query if exact_email else query + "%" if len(query) == 2 else "%" + query + "%"
                )
                match = (
                    "lower(email) = lower(:pattern) "
                    if exact_email
                    else "(lower(name) LIKE lower(:pattern) OR lower(email) LIKE lower(:pattern)) "
                )
                query_sql = (
                    'SELECT id, name, email FROM directory_bench WHERE "emailVerified" IS TRUE '
                    "AND CAST(id AS text) <> :subject "
                    + "AND "
                    + match
                    + "ORDER BY name, id LIMIT 20"
                )
                statement = text(query_sql)
                parameters = {"pattern": pattern, "subject": "0"}
                db.execute(statement, parameters).all()
                samples = []
                for _ in range(20):
                    start = perf_counter()
                    db.execute(statement, parameters).all()
                    samples.append((perf_counter() - start) * 1000)
                samples.sort()
                print(
                    f"{query!r}: p50={statistics.median(samples):.2f} ms, p95={samples[18]:.2f} ms"
                )
                plan = db.execute(
                    text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + query_sql),
                    parameters,
                ).scalars()
                print("\n".join(plan))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
