"""Disposable synthetic development tables, without production ownership or RLS."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dev_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(currency) = 3", name="account_currency_length"),
    )
    op.create_table(
        "dev_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("dev_accounts.id"), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor != 0", name="transaction_nonzero"),
        sa.CheckConstraint(
            "amount_minor BETWEEN -9000000000000000 AND 9000000000000000",
            name="transaction_amount_range",
        ),
    )
    op.create_index("ix_dev_transactions_account_id", "dev_transactions", ["account_id"])


def downgrade() -> None:
    # Destructive: only for disposable development data. Use backups/forward fixes for real data.
    op.drop_index("ix_dev_transactions_account_id", table_name="dev_transactions")
    op.drop_table("dev_transactions")
    op.drop_table("dev_accounts")
