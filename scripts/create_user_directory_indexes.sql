-- Read docs/user-directory-search.md before running this on a verified database.
-- Run with psql and a direct owner connection, with autocommit enabled.
-- Do not wrap in BEGIN: CREATE INDEX CONCURRENTLY cannot run in a transaction.
-- This file is a reviewed deployment artifact; it is not run by app startup.
\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX CONCURRENTLY shonchoy_user_name_prefix_idx
  ON neon_auth."user" (lower(name) text_pattern_ops)
  WHERE "emailVerified" IS TRUE;

CREATE INDEX CONCURRENTLY shonchoy_user_email_prefix_idx
  ON neon_auth."user" (lower(email) text_pattern_ops)
  WHERE "emailVerified" IS TRUE;

CREATE INDEX CONCURRENTLY shonchoy_user_name_trgm_idx
  ON neon_auth."user" USING gin (lower(name) gin_trgm_ops)
  WHERE "emailVerified" IS TRUE;

CREATE INDEX CONCURRENTLY shonchoy_user_email_trgm_idx
  ON neon_auth."user" USING gin (lower(email) gin_trgm_ops)
  WHERE "emailVerified" IS TRUE;
