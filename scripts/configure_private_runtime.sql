-- Run once as the database owner AFTER `uv run alembic upgrade head`.
-- Set the login password privately using psql's \password shonchoy_runtime.
-- The runtime role never owns tables and cannot bypass row-level security.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shonchoy_runtime') THEN
    CREATE ROLE shonchoy_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END $$;
-- Neon owners cannot ALTER SUPERUSER/BYPASSRLS attributes, even to disable them.
-- Fail closed if a pre-existing role is privileged rather than silently reusing it.
DO $$ BEGIN
  IF EXISTS (
    SELECT FROM pg_roles WHERE rolname = 'shonchoy_runtime'
      AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolbypassrls OR NOT rolcanlogin)
  ) THEN
    RAISE EXCEPTION 'shonchoy_runtime must be an unprivileged LOGIN NOINHERIT role';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public, neon_auth TO shonchoy_runtime;
GRANT SELECT (id, "userId", "expiresAt") ON neon_auth.session TO shonchoy_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  core_users, core_workspaces, core_accounts, core_balance_observations,
  core_category_groups, core_categories, core_transactions, core_rules,
  core_budgets, core_recurring, core_idempotency, core_audit_events, core_outbox,
  feedback_categories, feedback_entries, feedback_interests, feedback_category_changes
TO shonchoy_runtime;
