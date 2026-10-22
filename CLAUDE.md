# Claude Instructions: Shonchoy Backend

This document guides Claude when working with the Python FastAPI & LangGraph backend services in `shonchoy-backend/`.

## Quick Reference Commands

Execute from `shonchoy-backend/` (or via the root workspace scripts):

- **Synchronize Environment**: `uv sync --locked`
- **Run Core Financial API**: `.venv/bin/python -m uvicorn fintrack_core.main:create_app --factory --host 127.0.0.1 --port 8000 --reload`
- **Run Financial Advisor**: `.venv/bin/python -m uvicorn fintrack_advisor.main:create_app --factory --host 127.0.0.1 --port 8001 --reload`
- **Execute Full Quality Gate**: `.venv/bin/python scripts/check.py` (runs ruff, mypy, pytest, bandit, pip-audit, and openapi export)
- **Run Database Migrations**: `.venv/bin/python -m alembic upgrade head`
- **Export OpenAPI Specification**: `.venv/bin/python scripts/export_openapi.py`

## Architectural Guidelines

1. **Separation of Services**:
   - `fintrack_core`: Deterministic, transactional financial ledger and state machine. Uses async SQLAlchemy and PostgreSQL (Neon).
   - `fintrack_advisor`: LangGraph agent runtime. Operates as an isolated advisory service with read-only query capabilities against the core.
2. **Hexagonal Architecture**:
   - Keep business logic in `src/fintrack_core/finance/domain.py` free of framework or ORM dependencies.
   - Use ports in `ports.py` and adapters in `persistence.py` and `http.py`.
3. **Optimistic Locking & Concurrency**:
   - Every financial aggregate root has a `version` integer.
   - Updates must check `If-Match` against the current version and increment on write. Return HTTP 412 on mismatch.
4. **Idempotent Commands**:
   - Mutating routes require an `Idempotency-Key` header to protect against network retries.

For comprehensive agent invariants and security guidelines, see [AGENTS.md](AGENTS.md).
