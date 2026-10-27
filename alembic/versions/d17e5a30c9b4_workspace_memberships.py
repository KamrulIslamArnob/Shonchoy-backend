"""Recover the membership revision from the verified deployed schema.

The deployed database already records this revision. Restoring its DDL keeps
fresh installations and existing databases on the same lineage without stamping.
"""

import sqlalchemy as sa

from alembic import op

revision = "d17e5a30c9b4"
down_revision = "c862fe8410ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_memberships",
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("subject", name="core_memberships_pkey"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["core_workspaces.id"], name="core_memberships_workspace_id_fkey"
        ),
        sa.CheckConstraint("role = 'owner'", name="ck_core_memberships_role"),
    )
    op.create_index("ix_core_memberships_workspace_id", "core_memberships", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_core_memberships_workspace_id", table_name="core_memberships")
    op.drop_table("core_memberships")
