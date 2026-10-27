# Consolidate development database branches

## Intended result

Use `shonchoy-mobile-auth-dev` for both managed authentication and finance.
Move required application schema/data from `fintrack-backend-dev` after comparison.
Keep `production` separate. Retain both original development branches until the
combined database passes verification. This is a data migration, not a branch reset.

## Access needed

In the backend's ignored `.env`, set `FINTRACK_AUTH_DATABASE_URL` to the PostgreSQL
connection string for `shonchoy-mobile-auth-dev`. The HTTPS Auth endpoint is not a
PostgreSQL connection string. Consolidation requires a migration-capable role;
normal runtime access must use restricted roles. Never paste credentials into chat.

## Execution sequence

1. Inspect both databases read-only: schema, migration revisions, table counts,
   primary/foreign keys, overlapping IDs, user ownership and row-level policies.
2. Create recoverable backups of both branches before writes. Verify restoration
   on an isolated candidate branch. Pause application writes during final copying.
3. Rehearse the migration on the candidate. Apply compatible finance migrations
   and explicitly selected application rows in dependency order. Report divergent
   rows for resolution instead of overwriting them. Preserve UUIDs, amounts,
   relationships and audit history; do not assign shared legacy records to users.
4. Preserve the target's managed `neon_auth` schema, Google configuration and user
   IDs. Do not copy session/signing-key/provider tables between Auth environments.
5. Verify record counts, balances, foreign keys, migration head, two-user privacy,
   revoked sessions and real PostgreSQL RLS under restricted runtime credentials.
6. After successful validation, use the target branch for finance runtime and
   direct migration URLs. Keep frontend/backend Auth URLs on this same branch;
   a separate `FINTRACK_AUTH_DATABASE_URL` is then unnecessary. Restart services
   and verify browser login, workspace loading, create/read and sign-out.

No branch has been reset, deleted or merged. Execution is waiting for target
connection access; backup and conflict checks must precede any database writes.
