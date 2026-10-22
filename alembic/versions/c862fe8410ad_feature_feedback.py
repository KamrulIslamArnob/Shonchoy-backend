"""Feature feedback and explicit interest; additive development tables."""

import sqlalchemy as sa

from alembic import op

revision = "c862fe8410ad"
down_revision = "b4a91c7849e2"
branch_labels = None
depends_on = None


def row_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_id", sa.Uuid(), sa.ForeignKey("core_workspaces.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "feedback_categories",
        *row_columns(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(160), nullable=False),
        sa.Column("feature_key", sa.String(60), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("id", "scope_id"),
        sa.UniqueConstraint("scope_id", "feature_key", "name_key"),
    )
    for table in ("feedback_entries", "feedback_interests"):
        columns = row_columns() + [
            sa.Column("feature_key", sa.String(60), nullable=False),
            sa.Column("segment", sa.String(60), nullable=False),
            sa.Column("source", sa.String(120), nullable=False),
            sa.Column("subject_ref", sa.String(80), nullable=False),
        ]
        if table == "feedback_entries":
            op.create_table(
                table,
                *columns,
                sa.Column("category_id", sa.Uuid(), nullable=True),
                sa.Column("message", sa.String(4000), nullable=False),
                sa.ForeignKeyConstraint(
                    ["category_id", "scope_id"],
                    ["feedback_categories.id", "feedback_categories.scope_id"],
                ),
                sa.CheckConstraint("length(message) BETWEEN 1 AND 4000"),
            )
        else:
            op.create_table(
                table, *columns, sa.UniqueConstraint("scope_id", "subject_ref", "feature_key")
            )
        for column in ("feature_key", "segment"):
            op.create_index(f"ix_{table}_{column}", table, [column])
    for table in ("feedback_categories", "feedback_entries", "feedback_interests"):
        op.create_index(f"ix_{table}_scope_id", table, ["scope_id"])
    op.create_table(
        "feedback_category_changes",
        *row_columns(),
        sa.Column(
            "category_id", sa.Uuid(), sa.ForeignKey("feedback_categories.id"), nullable=False
        ),
        sa.Column("actor_id", sa.String(80), nullable=False),
        sa.Column("client", sa.String(40), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_feedback_category_changes_scope_id", "feedback_category_changes", ["scope_id"]
    )


def downgrade() -> None:
    # Export feedback first: downgrade removes only this module's records.
    for table in (
        "feedback_category_changes",
        "feedback_interests",
        "feedback_entries",
        "feedback_categories",
    ):
        op.drop_table(table)
