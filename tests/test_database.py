import os
import subprocess
import sys
from pathlib import Path

import pytest

from fintrack_core.database import build_engine, postgres_url


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "postgresql://u:p@host/db",
        "postgresql://u:p@host/db?sslmode=disable",
        "not a URL",
    ],
)
def test_url_requires_postgres_tls_and_redacts_invalid_input(url):
    with pytest.raises(ValueError) as error:
        postgres_url(url)
    assert url not in str(error.value)


def test_neon_url_preserves_connection_options_and_uses_no_pool():
    url = postgres_url("postgresql://synthetic:dummy@ep-test-pooler.example/db?sslmode=require")
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"
    engine = build_engine(url.render_as_string(hide_password=False))
    assert type(engine.pool).__name__ == "NullPool"
    engine.dispose()


def test_postgres_migration_offline_upgrade_and_destructive_downgrade():
    root = Path(__file__).parents[1]
    env = {
        **os.environ,
        "FINTRACK_MIGRATION_DATABASE_URL": "postgresql://synthetic:dummy@ep-synthetic.example/dev?sslmode=require",
    }
    for revision, direction, expected in [
        ("head", "upgrade", "CREATE TABLE dev_transactions"),
        ("0001:base", "downgrade", "DROP TABLE dev_accounts"),
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, revision, "--sql"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert expected in result.stdout
        assert "dummy" not in result.stdout


def test_migration_refuses_pooled_neon_url():
    env = {
        **os.environ,
        "FINTRACK_MIGRATION_DATABASE_URL": "postgresql://synthetic:dummy@ep-test-pooler.example/dev?sslmode=require",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Migrations require the direct Neon URL" in result.stderr
    assert "dummy" not in result.stderr
