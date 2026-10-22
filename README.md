# FinTrack Python backend

Two independent FastAPI processes: core REST API (`fintrack_core`, port 8000) and isolated offline LangGraph advisor (`fintrack_advisor`, port 8001). The web and mobile prototypes keep their existing local behavior. This is synthetic development scaffolding with one development bearer token per process; production identity, household authorization/RLS, idempotency, audit/outbox and frontend cutover remain in PR-0023, PR-0024 and PR-0036. Never use real financial records here.

## Install and run

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required. Dependencies, including development tools, are locked in `uv.lock`. From the workspace root:

```sh
uv sync --project backend --locked
npm run backend:init
npm run backend:dev
# In another terminal:
npm run advisor:dev
```

This workspace also has a local uv executable at `.local/tools/backend/bin/uv`; use that path if uv is not on PATH. Initialization preserves existing values and creates ignored `backend/.env` and `backend/.env.advisor` with different private random tokens, mode 0600. Settings files are resolved from the `backend/` working directory. The advisor reads only `.env.advisor`; give a deployed advisor its own environment with no database variables or database network access.

- Core Swagger UI: <http://127.0.0.1:8000/docs>
- Advisor Swagger UI: <http://127.0.0.1:8001/docs>
- Both: `/health/live` is public; `/v1/health/ready` requires the process's bearer token.
- Both: `/v1/openapi.json` is the credential-free OpenAPI contract.

Copy your local token into Swagger's **Authorize** field for synthetic requests. The token is a single-workspace development gate, not a user session, household membership, role or production authentication. Missing/short tokens deny resource access with 503; missing/wrong bearer tokens get 401. Commands bind to loopback and disable access logging. Never expose these processes publicly.

## Neon database

Configured project: `winter-surf-88756036`. Supplied parent: `br-billowing-star-b4ih39ph` (`production`). The scaffold targets schema-only development branch `fintrack-backend-dev` (`br-calm-truth-b4ghgt7x`). Use the development branch explicitly; the MCP project filter does not pin SQL operations to a branch.

The official `neon` and `neon-postgres` skills are installed locally for Claude Code and Codex. `.codex/config.toml` and `.mcp.json` declare the hosted Streamable HTTP MCP endpoint scoped to this project. OAuth credentials live in the client's local credential store. Restart/reconnect the coding client to load newly installed MCP tools. The MCP server is development tooling; the backend uses psycopg directly and does not call MCP.

After Neon CLI sign-in:

```sh
npx neon@latest auth
npm run backend:connect
npm run backend:migrate
```

`backend:connect` fetches both URLs for the exact project/branch, preserves existing non-empty settings and writes credentials only to ignored `backend/.env` (0600), without displaying them. It does not create projects, change branch settings, activate other Neon services or apply schema changes.

| Setting | Purpose | Missing value |
| --- | --- | --- |
| `FINTRACK_DATABASE_URL` | Pooled Neon PostgreSQL URL for core API only | Liveness/docs work; resource routes and readiness return 503 |
| `FINTRACK_MIGRATION_DATABASE_URL` | Direct non-pooler URL for explicit Alembic migrations | Migrations fail |
| `FINTRACK_DEV_API_KEY` | Random core development bearer token, at least 32 characters | Protected routes return 503 |
| `FINTRACK_FEEDBACK_ADMIN_KEY` | Separate random feedback admin token, initialized privately by `scripts/init_local.py`; never sent to browsers | Feedback admin routes return 503 |
| `FINTRACK_CORS_ORIGINS` | JSON array of exact local frontend origins | Defaults to localhost/127.0.0.1 on port 5173 |
| `FINTRACK_ADVISOR_DEV_API_KEY` | Separate random token in `.env.advisor` | Advisor routes return 503 |

URLs must use PostgreSQL with `sslmode=require`, `verify-ca`, or `verify-full`. Standard `postgresql://` URLs are normalized to the psycopg SQLAlchemy dialect, preserving query options. Connections use `NullPool` with connect/query timeouts. Migrations require a direct hostname. Never put these values in `VITE_*`, chat, source or screenshots. Revoke database credentials in Neon and replace the private file if exposed; rotate development tokens by replacing their private values and restarting the appropriate process.

## Connected core API

The [implemented `/v1/core` API](../docs/core-api.md) adds profile/preferences, manual accounts/observations, categories/groups/rules, transactions/review/splits/paired transfers, budgets/rollover, recurring projections and summary reads. Its commands require idempotency keys and versioned edits; SQL changes, audit and pending outbox commit together. This is the single-workspace development token boundary. Existing `/v1` scaffold endpoints below remain separate and compatible. Run migrations before using core endpoints.

## Legacy scaffold REST format

| Method and path | Purpose |
| --- | --- |
| `GET /v1/accounts` | Cursor-paginated synthetic accounts |
| `POST /v1/accounts` | Create `{ "name": "Synthetic cash", "currency": "BDT" }` |
| `GET /v1/accounts/{id}` | Read one account |
| `GET /v1/transactions` | Cursor pagination; optional `accountId` filter |
| `POST /v1/transactions` | Create synthetic booked record |
| `GET /v1/transactions/{id}` | Read one transaction |
| `POST /v1/agent/runs` (advisor) | Run `{ "message": "List capabilities" }` |

Success: `{ "ok": true, "data": ..., "requestId": "..." }`. Lists place `items` and `nextCursor` inside `data`; `limit` defaults to 50 and is bounded to 1–100. Pass `nextCursor` as `cursor` for the next page. UUID sort gives deterministic traversal, not a snapshot across concurrent inserts. The server generates IDs and timestamps, rejects unknown fields (including spoofed owner/role/household fields), and returns `X-Request-Id` and `Cache-Control: no-store`.

Errors use `application/problem+json` with `type`, `title`, `status`, `code`, `detail`, `requestId` and sanitized `fieldErrors`. Validation never echoes input values. Unexpected/database/graph failures return sanitized messages. The scaffold returns a top-level problem document; the frontend adapter in PR-0022 must map it to the PRD's client-side `ApiResult` union. Production contract reconciliation remains PR-0023.

Transaction example (currency inherited from its account):

```json
{
  "accountId": "00000000-0000-4000-8000-000000000001",
  "amountMinor": -12345,
  "description": "Synthetic expense",
  "bookedOn": "2026-10-20"
}
```

Amounts are signed integers, nonzero, bounded to ±9 quadrillion minor units (within JavaScript's safe integer range). Negative means outflow; positive means inflow. Supported scaffold currencies are BDT, USD, EUR and GBP, all two decimal places. This is a raw booked-record scaffold: no computed balance, transfer pairing, refund classification, splits, budgets, categories or authoritative totals are implemented. PR-0005 supplies the full money contract.

POST requests are **not idempotent**: repeating a successful create makes a new record. Do not automatically retry writes. There is no edit/delete/archive or optimistic concurrency yet. Database failure rolls back the session, returns 503, and leaves retry decisions with the caller.

## Schema and recovery

Legacy Alembic revision `0001` creates only `dev_accounts`, `dev_transactions`, their checks/index and a dedicated migration-version table. The additive core revision creates separate `core_` tables. Startup never creates or changes tables. Use only disposable synthetic development databases. Before a migration, verify branch identity and preserve any existing application state; do not apply to production.

```sh
cd backend
.venv/bin/python -m alembic current
.venv/bin/python -m alembic upgrade head
# Destructive: disposable synthetic tables only
.venv/bin/python -m alembic downgrade base
```

Downgrade removes all scaffold accounts and transactions. Recreate with `upgrade head`; it does not restore deleted data. Real backups, Neon restore rehearsal and retention policy remain production requirements under PR-0004. Never run downgrade against user data. Stopping/removing the backend leaves the browser demo storage untouched.

## LangGraph foundation

A compiled `StateGraph` routes a message either through a static allowlisted capabilities tool or directly to a response node, then ends. Runs use an eight-step recursion bound and a ten-second request timeout. Responses explicitly identify `mode: offline_stub`. There is no LLM, model credential, database access, financial write tool, retained conversation/checkpointer or telemetry enabled by this setup. Future providers replace the responder behind a separately reviewed adapter; user-scoped read tools must call authenticated core APIs under ADR-0002. Do not give the advisor database credentials.

## Checks and contracts

```sh
npm run backend:check
npm run backend:openapi
# Explicit live, verified development branch only:
npm run backend:test:postgres
npm run quality:feature
```

The backend gate checks lock consistency, Ruff lint/format, strict mypy, pytest, Bandit, dependency advisories from hashed uv exports, and OpenAPI generation. Every failure or unavailable tool fails the gate. Evidence is UTC-stamped under ignored `.local/reports/backend/`; OpenAPI exports are under `.local/backend/openapi/`. The workspace feature gate requires this backend gate in addition to all existing web checks. SQLite API integration tests verify local application behavior; offline PostgreSQL migration SQL does not prove live Neon behavior. Live smoke evidence is recorded separately in the ticket. From `backend/`, `.venv/bin/python scripts/smoke_neon.py` verifies that the configured URL matches the scaffold development branch, runs a synthetic API roundtrip inside an outer transaction, and rolls it back. It never applies migrations.

The Python package/API scaffold version is `0.1.0`, independent of the workspace release in `VERSION` and of Alembic revision `0001`; workspace releases continue only through `ticket:close`. Contract compatibility/client generation and deployment remain future work.

References: [FastAPI modular applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [Neon MCP](https://neon.com/docs/ai/neon-mcp-server), [Neon SQLAlchemy](https://neon.com/docs/guides/sqlalchemy), [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview).

## Next implementation plan

See the [frontend-aligned API and concurrency plan](../docs/backend-api-plan.md) for proposed module/use-case/repository boundaries, financial contracts, atomic version/idempotency controls, worker coordination and client cutover. These controls are requirements for future tickets, not capabilities of this scaffold.
