# FinTrack Python Backend

Two independent FastAPI processes:
- **Core Financial REST API** (`fintrack_core`, port 8000)
- **Isolated Offline LangGraph Advisor** (`fintrack_advisor`, port 8001)

The `/v1/core` finance API requires a verified Neon user JWT and live managed session (`Authorization: Bearer <token>` and `X-Neon-Session-Id: <id>`), and provisions a private workspace per identity.
See [docs/WORKSPACE_SETUP_AND_ARCHITECTURE_GUIDE.md](docs/WORKSPACE_SETUP_AND_ARCHITECTURE_GUIDE.md) and [docs/private-authentication.md](docs/private-authentication.md).

---

## 1. Prerequisites & Installation

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required. Dependencies are strictly locked in `uv.lock`.

From the repository root:
```bash
# Set up Python virtual environment and install locked dependencies
cd shonchoy-backend
uv sync --locked
cd ..
```

Or within `shonchoy-backend`:
```bash
uv sync --locked
```

---

## 2. Neon Database & Single Production Branch Rule

> [!IMPORTANT]
> **Single Production Branch Policy**:  
> Project: `FinTrack_DB` (`winter-surf-88756036`)  
> Database: `neondb`  
> Branch: **`production`** (`br-billowing-star-b4ih39ph`)  
> **Never create or recreate development, staging, or preview branches on Neon.** Both authentication and financial data reside on this single production branch. (Former dev branches were consolidated and deleted on 2026-10-27).

### Role Configuration:
Application runtime connections use the restricted `shonchoy_runtime` role (configured via `scripts/configure_private_runtime.sql`) which enforces PostgreSQL Row-Level Security (RLS) on all tenant tables and has read-only access to `neon_auth.session`. Migrations use the database owner through the direct endpoint.

---

## 3. Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

| Setting | Purpose | Missing Value Behavior |
| :--- | :--- | :--- |
| `FINTRACK_DATABASE_URL` | Pooled Neon PostgreSQL URL for restricted role `shonchoy_runtime` | Liveness works; resource routes return 503 |
| `FINTRACK_MIGRATION_DATABASE_URL` | Direct non-pooler URL for Alembic migrations (database owner) | Migrations fail |
| `FINTRACK_NEON_AUTH_URL` | Managed Neon Auth endpoint matching frontend | Auth returns 401/503 |
| `FINTRACK_COMMAND_FINGERPRINT_KEY` | Server-only random secret (at least 32 characters) for command idempotency | Startup warning/error |
| `FINTRACK_ENABLE_DEVELOPMENT_ROUTES` | Keep `false` for tenant isolation (legacy scaffold disabled) | Defaults to false |
| `FINTRACK_CORS_ORIGINS` | JSON array of allowed origins (e.g. `["http://localhost:5173"]`) | Defaults to localhost |

---

## 4. Database Migrations

Always inspect current revision before migrating:
```bash
uv run alembic current
```
Apply migrations:
```bash
uv run alembic upgrade head
```
Or from monorepo root:
```bash
npm run backend:migrate
```

*Note on lineage: Revision `d17e5a30c9b4` preserves historical workspace memberships, and `d531c682a4f0` enforces private user workspaces and PostgreSQL Row-Level Security.*

---

## 5. Running the Backend Services

From repository root:
```bash
# Core Financial REST API (Port 8000)
npm run backend:dev

# Financial Advisor Runtime (Port 8001)
npm run advisor:dev
```

### Endpoints & Docs:
- **Core API Swagger UI**: `http://127.0.0.1:8000/docs`
- **Advisor API Swagger UI**: `http://127.0.0.1:8001/docs`
- **Public Liveness**: `http://127.0.0.1:8000/health` or `/health/live`
- **OpenAPI Schema Export**: `npm run backend:openapi`

---

## 6. Verification & Quality Gates

Run all 9 backend verification checks before submitting changes:
```bash
# From workspace root
npm run backend:check

# Or from shonchoy-backend directory:
uv run python scripts/check.py
```
This verifies:
1. `uv lock --check`
2. Audit export
3. `ruff check .`
4. `ruff format --check .`
5. `mypy` (strict static typing)
6. `pytest` (unit & integration tests)
7. `bandit` (static security analysis)
8. `pip-audit`
9. `export_openapi.py` (contract export)

---

## 7. Financial & Security Invariants

1. **Integer Minor Units**: All money amounts must be signed integers representing minor currency units (paisa/cents). Floating-point currency is strictly banned.
2. **Double-Entry Guarantees**: Balance equality must be preserved on all transfers.
3. **No Direct Mutation from AI Advisor**: The LangGraph advisor agent cannot mutate the database directly; it returns structured proposals for human confirmation.
4. **Row-Level Security**: Every financial query must execute inside a transaction where `set_config('app.workspace_id', :ws, true)` is set.
5. **Zero Credentials in Git**: Never commit `.env` files or connection strings.
