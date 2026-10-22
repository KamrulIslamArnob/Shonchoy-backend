"""brandfetch_asset_pipeline

Revision ID: b4a91c7849e2
Revises: 88acead366a1
Create Date: 2026-10-22 02:45:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "b4a91c7849e2"
down_revision = "88acead366a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Canonical Brands Table
    op.create_table(
        "brands",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("bf_brand_id", sa.Text(), nullable=True),
        sa.Column("bf_urn", sa.Text(), nullable=True),
        sa.Column("canonical_domain", sa.Text(), nullable=False),
        sa.Column("bf_domain", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("links", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("company", sa.JSON(), nullable=True),
        sa.Column("colors", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("fonts", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("palette", sa.JSON(), nullable=True),
        sa.Column(
            "palette_degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("quality_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("is_nsfw", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_claimed", sa.Boolean(), nullable=True),
        sa.Column("visual_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "license_expires_at", sa.DateTime(timezone=True), nullable=True
        ),  # visual + 30 days
        sa.Column("context_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "context_expires_at", sa.DateTime(timezone=True), nullable=True
        ),  # context + 30 days
        sa.Column("merged_into_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'merged' OR merged_into_id IS NOT NULL", name="merged_has_target"
        ),
        sa.ForeignKeyConstraint(["merged_into_id"], ["brands.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bf_brand_id"),
        sa.UniqueConstraint("bf_urn"),
        sa.UniqueConstraint("canonical_domain"),
    )

    # 2. Brand Assets Table
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("bf_asset_id", sa.Text(), nullable=True),
        sa.Column("bf_src_url", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("transparent", sa.Boolean(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),  # brandfetch | manual
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
        ),  # NULL for source='manual'
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "brand_id", "variant", "theme", "format", "content_hash", name="uq_brand_asset_variant"
        ),
    )

    # 3. Item Provenance & State Table
    op.create_table(
        "brand_items",
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("brand_id", "item_key"),
    )

    # 4. Brand Aliases Table
    op.create_table(
        "brand_aliases",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("alias_type", sa.Text(), nullable=False),
        sa.Column("alias_value", sa.Text(), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_type", "canonical_key", name="uq_brand_alias_lookup"),
    )

    # 5. Brandfetch Credit Ledger Table
    op.create_table(
        "brandfetch_credit_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("x_bf_error", sa.Text(), nullable=True),
        sa.Column("charged", sa.Boolean(), nullable=False),
        sa.Column("quota_remaining", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("brandfetch_credit_ledger")
    op.drop_table("brand_aliases")
    op.drop_table("brand_items")
    op.drop_table("brand_assets")
    op.drop_table("brands")
