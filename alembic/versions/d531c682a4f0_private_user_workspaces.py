"""Private managed users, ownership constraints, and transaction-scoped RLS.

Existing development records are preserved and never assigned to new identities.
"""

import sqlalchemy as sa

from alembic import op

revision = "d531c682a4f0"
down_revision = "d17e5a30c9b4"
branch_labels = None
depends_on = None

SCOPED = (
    "core_accounts",
    "core_balance_observations",
    "core_category_groups",
    "core_categories",
    "core_transactions",
    "core_rules",
    "core_budgets",
    "core_recurring",
    "core_idempotency",
    "core_audit_events",
    "core_outbox",
    "feedback_categories",
    "feedback_entries",
    "feedback_interests",
    "feedback_category_changes",
)
RELATIONS = (
    ("core_categories", "group_id", "core_category_groups"),
    ("core_transactions", "category_id", "core_categories"),
    ("core_rules", "account_id", "core_accounts"),
    ("core_rules", "set_category_id", "core_categories"),
    ("core_recurring", "account_id", "core_accounts"),
    ("core_outbox", "event_id", "core_audit_events"),
)
UNIQUE = ("core_category_groups", "core_categories", "core_audit_events")


def upgrade() -> None:
    op.create_table(
        "core_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("auth_issuer", sa.String(500), nullable=False),
        sa.Column("auth_subject", sa.String(255), nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("core_workspaces.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("auth_issuer", "auth_subject"),
    )
    for table in UNIQUE:
        op.create_unique_constraint(f"uq_{table}_owner", table, ["id", "scope_id"])
    for table, column, target in RELATIONS:
        op.create_foreign_key(
            f"fk_{table}_{column}_owner", table, target, [column, "scope_id"], ["id", "scope_id"]
        )
    # Empty/missing transaction context denies reads and writes. FORCE also covers table owners;
    # deploy the runtime with a non-superuser, non-BYPASSRLS role.
    for table, column in [(name, "scope_id") for name in SCOPED] + [
        ("core_workspaces", "id"),
        ("core_users", "workspace_id"),
        ("core_memberships", "workspace_id"),
    ]:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        condition = f"\"{column}\"::text = NULLIF(current_setting('app.workspace_id', true), '')"
        op.execute(
            f'CREATE POLICY private_workspace ON "{table}" '
            f"USING ({condition}) WITH CHECK ({condition})"
        )
        op.execute(f'REVOKE ALL ON "{table}" FROM PUBLIC')
        # Do not expose finance tables through the Data API's shared SQL roles.
        for role in ("anonymous", "authenticated"):
            op.execute(
                f'DO $$ BEGIN REVOKE ALL ON "{table}" FROM "{role}"; '
                "EXCEPTION WHEN undefined_object THEN NULL; END $$"
            )


def downgrade() -> None:
    for table in (*SCOPED, "core_workspaces", "core_users", "core_memberships"):
        op.execute(f'DROP POLICY private_workspace ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table, column, _ in reversed(RELATIONS):
        op.drop_constraint(f"fk_{table}_{column}_owner", table, type_="foreignkey")
    for table in reversed(UNIQUE):
        op.drop_constraint(f"uq_{table}_owner", table, type_="unique")
    op.drop_table("core_users")
