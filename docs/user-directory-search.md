# User-directory search

Search requires a verified managed JWT and a live session on every request. The
directory route does not provision a finance workspace. It makes one session read
and one bounded profile read; PostgreSQL transaction setup may add statements.
Results contain at most 20 verified users and exclude the requester.

Two-character queries match the beginning of a name or email. Longer queries
match anywhere, while a complete email address is matched exactly. All use
case-insensitive matching, and wildcard characters are treated literally. The mobile client
debounces and cancels stale searches, and keeps a small session-scoped in-memory
cache. Account selection and shared-loan acceptance still need server-side
revalidation; the existing local contact record is not a shared loan.

## Index deployment

`scripts/create_user_directory_indexes.sql` is a deployment artifact, not an
automatic migration. It creates partial prefix and trigram expression indexes
matching the current query and installs `pg_trgm` if absent. The indexes affect
the managed `neon_auth."user"` table. First verify Neon permits the intended
owner to index that managed table and verify the target is the prescribed
production project and branch. Follow the production change process; nothing
in this repository applies the script automatically.

Use a direct owner connection with `psql` autocommit and execute the file with
`psql -X -v ON_ERROR_STOP=1 -f scripts/create_user_directory_indexes.sql`.
Supply the connection securely, not in shell history. `CREATE INDEX CONCURRENTLY`
cannot run inside a transaction. A failure may leave an invalid index; inspect
`pg_index.indisvalid` and `indisready` and the index definition before deciding
how to recover or retry. The script intentionally does not use `IF NOT EXISTS`
for indexes, so a conflicting or invalid index is not silently accepted. The
`pg_trgm` operator classes must be visible on the connection search path.

The database role used for authentication also needs the limited user-table
column grants documented in `private-authentication.md`. No production database
or role changes are made by the local test suite.

## Benchmark

Use a disposable **local** PostgreSQL database whose name begins with
`shonchoy_search_benchmark_`; the benchmark refuses non-loopback servers and
other database names. Set `FINTRACK_SEARCH_BENCHMARK_URL` privately to its URL,
then run `uv run python scripts/benchmark_user_directory.py`. The script creates
`pg_trgm` in that disposable database if needed and creates 100,000 synthetic
rows and all indexes in a temporary table. It prints warm, sequential p50/p95
query times and `EXPLAIN (ANALYZE, BUFFERS)` plans for prefix, substring,
non-ASCII and no-match queries. It does not claim end-to-end or concurrent-load
latency. Test realistic traffic, cold starts, Bengali collation behavior and the
actual managed-table permissions separately before setting a performance target.
