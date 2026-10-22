"""Dry-run by default; --apply adds scenarios only to the verified development endpoint."""

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fintrack_core.config import Settings
from fintrack_core.database import build_engine, postgres_url
from fintrack_core.finance.scenarios import seed_scenarios

EXPECTED_ENDPOINT = "ep-nameless-voice-b4fr2cc0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--as-of",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        default=datetime.now(ZoneInfo("Asia/Dhaka")).date(),
    )
    args = parser.parse_args()
    settings = Settings()
    if settings.database_url is None:
        raise SystemExit("Database is not configured.")
    raw = settings.database_url.get_secret_value()
    url = postgres_url(raw)
    host = url.host or ""
    endpoint = host.split(".")[0].removesuffix("-pooler")
    if endpoint != EXPECTED_ENDPOINT or url.database != "neondb":
        raise SystemExit("Refusing to seed an unverified database endpoint.")
    engine = build_engine(raw)
    try:
        with Session(engine) as db, db.begin():
            db.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext('shonchoy-scenario-v1'))"))
            counts = seed_scenarios(db, args.as_of)
            if not args.apply:
                db.rollback()
            print(json.dumps({"applied": args.apply, "as_of": str(args.as_of), "inserted": counts}))
    except SQLAlchemyError:
        raise SystemExit(
            "Seed failed; the complete transaction was rolled back. Details withheld."
        ) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
