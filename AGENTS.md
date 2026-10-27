# Agent Context: Shonchoy Backend

This document sets the system context, constraints, and operational protocols for AI agents working in `shonchoy-backend`.

> [!IMPORTANT]
> **Complete Setup & Architecture Guide**: Read the comprehensive **[Workspace Setup & Architecture Guide](docs/WORKSPACE_SETUP_AND_ARCHITECTURE_GUIDE.md)** before making any code or migration changes.

## Database: production branch only

- Use exactly one Neon database branch: `production` (`br-billowing-star-b4ih39ph`) in project `FinTrack_DB` (`winter-surf-88756036`), database `neondb`.
- Backend financial data and the mobile app's managed authentication must use this same production branch. Keep their authentication configuration synchronized.
- Do not create or recreate development, staging, preview, or temporary Neon branches, including for migrations or tests. Use local disposable databases for isolated tests; never run disposable-database cleanup against production.
- Before live database work, verify the project and branch IDs. Use the restricted runtime role for application access and the direct migration connection for migrations; keep credentials private.
- The former `fintrack-backend-dev` and `shonchoy-mobile-auth-dev` branches were consolidated into production and deleted with user confirmation on 2026-10-27.

## 1. Safety & Financial Invariants

1. **Integer Representation of Money**:
   - Currency amounts must be stored and processed as integers representing minor currency units (e.g., paisa for BDT, cents for USD). Never use floating-point types for currency in database columns or calculations.
2. **Double-Entry Balance Guarantees**:
   - Every transaction transfer must preserve balance equality between source and destination accounts.
   - Cash outflows and inflows must be recorded with directional signs and validated against account type restrictions.
3. **No Direct Mutation from AI Advisor**:
   - The AI advisor (`fintrack_advisor`) is strictly prohibited from invoking mutating database functions directly.
   - Advisor recommendations that involve creating budgets, adjusting limits, or logging transactions must be formatted as proposals for the user to approve through the frontend.
4. **Zero Check-in of Credentials**:
   - Never commit `.env` or database connection strings containing live credentials.
   - Use dummy fallback strings in tests and local development.

## 2. Verification Protocol

Before finishing any task in this section, verify:
1. `uv lock --check` (Dependency lockfile integrity)
2. `.venv/bin/python -m ruff check .` (Linter)
3. `.venv/bin/python -m ruff format --check .` (Formatter)
4. `.venv/bin/python -m mypy` (Type checker)
5. `.venv/bin/python -m pytest` (Unit & integration test suite)
6. `.venv/bin/python -m bandit -r src alembic -q` (Static security analysis)
7. Or simply run `.venv/bin/python scripts/check.py`, which executes all the above.

## 3. Directory Layout

- `src/fintrack_core/`: Core financial REST API, domain models, and Neon Postgres persistence.
- `src/fintrack_advisor/`: LangGraph intelligent advisor runtime and isolated tools.
- `src/fintrack_common/`: Shared API models, exceptions, and serialization helpers.
- `alembic/`: Database migration scripts for Neon Postgres.
- `scripts/`: Operational tools (`check.py`, `init_local.py`, `connect_neon.py`, `export_openapi.py`).
- `tests/`: Automated unit and integration tests.

For command shortcuts, see [CLAUDE.md](CLAUDE.md). For schema and API architecture, see [DESIGN.md](DESIGN.md).

