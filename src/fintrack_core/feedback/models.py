from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fintrack_core.finance.models import Row


class FeedbackCategory(Row):
    __tablename__ = "feedback_categories"
    __table_args__ = (
        UniqueConstraint("id", "scope_id"),
        UniqueConstraint("scope_id", "feature_key", "name_key"),
    )
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(160))
    feature_key: Mapped[str] = mapped_column(String(60), default="")
    archived: Mapped[bool] = mapped_column(default=False)


class FeedbackEntry(Row):
    __tablename__ = "feedback_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "scope_id"], ["feedback_categories.id", "feedback_categories.scope_id"]
        ),
        CheckConstraint("length(message) BETWEEN 1 AND 4000"),
    )
    feature_key: Mapped[str] = mapped_column(String(60), index=True)
    segment: Mapped[str] = mapped_column(String(60), index=True)
    source: Mapped[str] = mapped_column(String(120))
    subject_ref: Mapped[str] = mapped_column(String(80))
    category_id: Mapped[UUID | None] = mapped_column(default=None)
    message: Mapped[str] = mapped_column(String(4000))


class FeatureInterest(Row):
    __tablename__ = "feedback_interests"
    __table_args__ = (UniqueConstraint("scope_id", "subject_ref", "feature_key"),)
    feature_key: Mapped[str] = mapped_column(String(60), index=True)
    segment: Mapped[str] = mapped_column(String(60), index=True)
    source: Mapped[str] = mapped_column(String(120))
    subject_ref: Mapped[str] = mapped_column(String(80))


class FeedbackCategoryChange(Row):
    __tablename__ = "feedback_category_changes"
    category_id: Mapped[UUID] = mapped_column(ForeignKey("feedback_categories.id"))
    actor_id: Mapped[str] = mapped_column(String(80))
    client: Mapped[str] = mapped_column(String(40), default="local-admin-proxy")
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
