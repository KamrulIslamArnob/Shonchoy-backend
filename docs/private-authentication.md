# Private authentication

The local app/backend configuration now uses the same production branch for
auth and finance. See [production consolidation](production-consolidation.md)
for preserved data, live verification, recovery files, and pending branch cleanup.

The `/v1/core` API requires `Authorization: Bearer <Neon JWT>` and
`X-Neon-Session-Id: <managed session ID>`. The backend verifies EdDSA signatures
using its configured issuer's JWKS, checks issuer/audience/expiry with a bounded
30-second clock-skew allowance, and queries
`neon_auth.session` to confirm that session's owner and expiry on every request.
No frontend-supplied user/workspace ID establishes ownership. Invalid credentials
return 401; configuration/provider/database outages fail closed.

On first authorized access, `core_users` and `core_workspaces` are inserted
transactionally. `(auth_issuer, auth_subject)` is unique; the server derives the
workspace UUID from that identity, so concurrent logins and multiple devices
cannot create different workspaces. Existing shared development data is preserved
without assigning it to any new user. All command receipts and audit/outbox events
remain workspace-scoped.

## Configuration and migration

Set the private backend `.env`:

- `FINTRACK_NEON_AUTH_URL`: exact managed endpoint configured in the mobile app.
- `FINTRACK_AUTH_DATABASE_URL`: optional private connection to the authentication
  branch when it differs from the finance branch. Leave unset for a shared branch.
  Its restricted role needs only schema usage and SELECT on `neon_auth.session`
  columns `id`, `userId`, and `expiresAt`. Configure that role on the auth branch;
  finance runtime grants alone do not grant access to another branch.
- `FINTRACK_COMMAND_FINGERPRINT_KEY`: private random secret of at least 32 characters.
- `FINTRACK_DATABASE_URL`: pooled PostgreSQL URL for the restricted runtime role.
- `FINTRACK_MIGRATION_DATABASE_URL`: direct PostgreSQL URL for the migration role.
- `FINTRACK_CORS_ORIGINS`: JSON array of exact browser origins, including Expo web.
- `FINTRACK_ENABLE_DEVELOPMENT_ROUTES=false`: keep old unscoped scaffold disabled.

Run `uv sync --locked`, then `uv run alembic upgrade head`. Migration
`d531c682a4f0` adds user mappings, composite owner foreign keys, and forced row-level
security. Run `scripts/configure_private_runtime.sql` as the database owner, set
that role's password privately (`\password shonchoy_runtime` in psql), and use it
for the runtime URL. The runtime must not own tables, be superuser, or bypass RLS.
It receives read-only access to the managed session table's three required columns.

Revision `d17e5a30c9b4` was missing from this checkout. Its membership-table DDL
has been recovered from the deployed schema, and the private-user migration now
follows it. Check `uv run alembic current` before upgrading; do not stamp over an
unknown revision or remove existing membership/workspace records. Legacy
memberships are preserved and protected by RLS without assigning their data to
new login identities.

`GET /health` and `GET /health/live` are public liveness endpoints; success means
the process is running, not that authentication or database configuration works.
Restart an existing Uvicorn process after changing code (the manual launch does
not enable reload). Physical devices require `--host 0.0.0.0` and the computer's
LAN address; a web browser on this machine can use `http://localhost:8000`.

Each transaction sets `app.workspace_id` with `set_config(..., true)`. Missing
context denies access. PostgreSQL pooling cannot carry the previous request's
scope into another transaction. Direct Data API roles lose finance-table grants;
clients must use the authorized API.

## Verification

`uv run pytest tests/test_private_workspaces.py` uses real Ed25519-signed tokens
with mocked JWKS retrieval and a disposable SQLite database. It verifies separate
users/workspaces, cross-user read/write/reference denial, session revocation,
issuer/audience/expiry rejection, and isolated idempotency receipts. Run
`uv lock --check`, Ruff lint/format, mypy, pytest, and Bandit before release.

The PostgreSQL migration can be rendered with `uv run alembic upgrade head --sql`;
actual RLS enforcement requires a PostgreSQL integration run. No live database or
Google console configuration is applied by unit tests. The older backend still
lacks the mobile prototype's people/personal-lending and capture-specific APIs.

On a **local disposable PostgreSQL database** with a restricted runtime `.env`, opt in
to `tests_postgres/test_private_rls.py` by setting
`FINTRACK_RUN_PRIVATE_RLS_TESTS=true`, then run
`uv run pytest tests_postgres/test_private_rls.py`. It deliberately omits application
filters to test database isolation and missing-context denial, and refuses
superuser/BYPASSRLS/table-owner connections. It removes only its random test scopes.
Never point this disposable-database test at production or create a Neon branch
for it; the single-production-branch rule in `AGENTS.md` applies.
