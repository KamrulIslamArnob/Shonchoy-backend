"""Verify a migrated development branch using synthetic records in a rolled-back transaction."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fintrack_core.config import Settings
from fintrack_core.database import build_engine, postgres_url, session
from fintrack_core.main import create_app
from fintrack_core.models import Account

settings = Settings()
if not settings.database_url or not settings.dev_api_key:
    raise SystemExit("Configure the development database and token first.")
lookup = subprocess.run(
    [
        "npx",
        "--yes",
        "neon@8.8.0",
        "connection-string",
        "br-calm-truth-b4ghgt7x",
        "--project-id",
        "winter-surf-88756036",
        "--pooled",
    ],
    capture_output=True,
    text=True,
    timeout=30,
)
if lookup.returncode:
    raise SystemExit("Cannot verify the development branch target. Authenticate Neon CLI first.")
expected, actual = (
    postgres_url(lookup.stdout.strip()),
    postgres_url(settings.database_url.get_secret_value()),
)
if (actual.host, actual.database) != (expected.host, expected.database):
    raise SystemExit(
        "Refusing smoke writes: configured URL is not the scaffold development branch."
    )
engine = build_engine(settings.database_url.get_secret_value())
auth = {"Authorization": "Bearer " + settings.dev_api_key.get_secret_value()}
checks = []
try:
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "5s"
            checks.append("pooled TLS connection and transaction timeout")
            app = create_app(settings)

            def isolated_session():
                with Session(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                ) as db:
                    yield db

            app.dependency_overrides[session] = isolated_session
            with TestClient(app) as client:
                assert client.get("/v1/health/ready", headers=auth).status_code == 200
                assert client.get("/v1/accounts").status_code == 401
                response = client.post(
                    "/v1/accounts",
                    headers=auth,
                    json={"name": "Synthetic rollback smoke", "currency": "BDT"},
                )
                assert response.status_code == 201
                account_id = response.json()["data"]["id"]
                assert client.get(f"/v1/accounts/{account_id}", headers=auth).status_code == 200
                response = client.post(
                    "/v1/transactions",
                    headers=auth,
                    json={
                        "accountId": account_id,
                        "amountMinor": -12345,
                        "description": "Synthetic rollback smoke",
                        "bookedOn": "2026-10-20",
                    },
                )
                assert response.status_code == 201
                data = response.json()["data"]
                read = client.get(f"/v1/transactions/{data['id']}", headers=auth)
                assert read.json()["data"] == data
                assert data["amountMinor"] == -12345
                checks.append("live PostgreSQL API readiness auth account transaction roundtrip")
        finally:
            outer.rollback()
    with engine.connect() as connection:
        assert connection.scalar(select(Account.id).where(Account.id == UUID(account_id))) is None
    checks.append("outer transaction rollback leaves no smoke records")
except Exception as error:
    # Do not print connection exceptions, SQL parameters, response payloads or tokens.
    raise SystemExit(f"Live smoke failed: {type(error).__name__}; inspect privately.") from None
finally:
    engine.dispose()
output = Path(__file__).resolve().parents[2] / ".local" / "reports" / "backend" / "live-neon.json"
output.parent.mkdir(parents=True, exist_ok=True)
report = {
    "verifiedAt": datetime.now(UTC).isoformat(),
    "project": "winter-surf-88756036",
    "branch": "br-calm-truth-b4ghgt7x",
    "passed": True,
    "checks": checks,
}
output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
