"""Scoped feedback queries and atomic commands; transport never executes SQL."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from fintrack_core.feedback.models import (
    FeatureInterest,
    FeedbackCategory,
    FeedbackCategoryChange,
    FeedbackEntry,
)
from fintrack_core.feedback.schemas import (
    FeedbackCategoryCreate,
    FeedbackCategoryEdit,
    FeedbackCategoryRead,
    FeedbackContext,
    FeedbackEntryCreate,
    FeedbackEntryRead,
    FeedbackOrigin,
    FeedbackReceipt,
    FeedbackSummary,
)
from fintrack_core.finance.domain import Data, require
from fintrack_core.finance.persistence import DEV_SCOPE, SqlUnitOfWork


class FeedbackService:
    def __init__(self, db: Session, fingerprint_key: str, actor: str = "development-admin") -> None:
        self.db = db
        self.scope = DEV_SCOPE
        # Existing development mode has one server-owned synthetic subject, not real identity.
        self.subject = f"development:{self.scope}"
        self.uow = SqlUnitOfWork(db, fingerprint_key)
        self.actor = actor

    def _categories(self, feature: str | None = None) -> list[FeedbackCategory]:
        query = select(FeedbackCategory).where(FeedbackCategory.scope_id == self.scope)
        if feature is not None:
            query = query.where(
                FeedbackCategory.archived.is_(False),
                or_(FeedbackCategory.feature_key == "", FeedbackCategory.feature_key == feature),
            )
        return list(self.db.scalars(query.order_by(FeedbackCategory.name_key)))

    def context(self, feature: str) -> Data:
        def read(_: Any) -> Data:
            interested = (
                self.db.scalar(
                    select(FeatureInterest.id).where(
                        FeatureInterest.scope_id == self.scope,
                        FeatureInterest.subject_ref == self.subject,
                        FeatureInterest.feature_key == feature,
                    )
                )
                is not None
            )
            return FeedbackContext(
                interested=interested,
                categories=[
                    FeedbackCategoryRead.model_validate(row) for row in self._categories(feature)
                ],
            ).model_dump(mode="json")

        return self.uow.read(read)

    def interest(self, key: str, body: FeedbackOrigin) -> Data:
        def action(_: Any) -> Data:
            row = self.db.scalar(
                select(FeatureInterest).where(
                    FeatureInterest.scope_id == self.scope,
                    FeatureInterest.subject_ref == self.subject,
                    FeatureInterest.feature_key == body.feature_key,
                )
            )
            if row is None:
                row = FeatureInterest(
                    scope_id=self.scope, subject_ref=self.subject, **body.model_dump()
                )
                self.db.add(row)
                self.db.flush()
            return FeedbackReceipt.model_validate(row).model_dump(mode="json")

        return self.uow.command(key, "feedback.interest", body.model_dump(mode="json"), action)

    def submit(self, key: str, body: FeedbackEntryCreate) -> Data:
        def action(_: Any) -> Data:
            if body.category_id is not None:
                require(
                    any(row.id == body.category_id for row in self._categories(body.feature_key)),
                    "Choose an active category for this feature, or leave it uncategorized.",
                )
            row = FeedbackEntry(scope_id=self.scope, subject_ref=self.subject, **body.model_dump())
            self.db.add(row)
            self.db.flush()
            return FeedbackReceipt.model_validate(row).model_dump(mode="json")

        return self.uow.command(key, "feedback.submit", body.model_dump(mode="json"), action)

    def categories(self) -> Data:
        return self.uow.read(
            lambda _: {
                "items": [
                    FeedbackCategoryRead.model_validate(row).model_dump(mode="json")
                    for row in self._categories()
                ]
            }
        )

    def save_category(
        self,
        key: str,
        body: FeedbackCategoryCreate | FeedbackCategoryEdit,
        identifier: UUID | None = None,
        version: int | None = None,
    ) -> Data:
        def action(_: Any) -> Data:
            row = (
                self.db.scalar(
                    select(FeedbackCategory).where(
                        FeedbackCategory.id == identifier, FeedbackCategory.scope_id == self.scope
                    )
                )
                if identifier
                else None
            )
            if identifier:
                require(row is not None, "Category not found.", 404)
                require(
                    row is not None and row.version == version,
                    "Category changed. Reload before saving.",
                    409,
                )
            before = (
                FeedbackCategoryRead.model_validate(row).model_dump(mode="json") if row else None
            )
            feature = (
                row.feature_key
                if row
                else (body.feature_key or "")
                if isinstance(body, FeedbackCategoryCreate)
                else ""
            )
            duplicate = self.db.scalar(
                select(FeedbackCategory.id).where(
                    FeedbackCategory.scope_id == self.scope,
                    FeedbackCategory.feature_key == feature,
                    FeedbackCategory.name_key == body.name.casefold(),
                )
            )
            require(
                duplicate is None or duplicate == identifier,
                "A category with this name already exists for this feature.",
                409,
            )
            if row is None:
                row = FeedbackCategory(
                    scope_id=self.scope,
                    feature_key=feature,
                    name=body.name,
                    name_key=body.name.casefold(),
                )
                self.db.add(row)
            else:
                row.name, row.name_key = body.name, body.name.casefold()
                if isinstance(body, FeedbackCategoryEdit):
                    row.archived = body.archived
                row.version += 1
                row.updated_at = datetime.now(UTC)
            self.db.flush()
            after = FeedbackCategoryRead.model_validate(row).model_dump(mode="json")
            previous = self.db.scalar(
                select(FeedbackCategoryChange)
                .where(FeedbackCategoryChange.scope_id == self.scope)
                .order_by(FeedbackCategoryChange.created_at.desc())
                .limit(1)
            )
            previous_hash = previous.hash if previous else "0" * 64
            audit_id = uuid4()
            value = json.dumps(
                [
                    str(audit_id),
                    self.actor,
                    str(row.id),
                    before,
                    after,
                    previous_hash,
                    "local-admin-proxy",
                ],
                sort_keys=True,
                separators=(",", ":"),
            )
            self.db.add(
                FeedbackCategoryChange(
                    id=audit_id,
                    scope_id=self.scope,
                    category_id=row.id,
                    actor_id=self.actor,
                    before=before,
                    after=after,
                    previous_hash=previous_hash,
                    hash=hashlib.sha256(value.encode()).hexdigest(),
                )
            )
            return after

        payload = {
            **body.model_dump(mode="json"),
            "id": str(identifier) if identifier else None,
            "version": version,
            "actor": self.actor,
        }
        return self.uow.command(key, "feedback.category.save", payload, action)

    def _query(self, model: Any, feature: str | None, segment: str | None) -> Any:
        query = select(model).where(model.scope_id == self.scope)
        if feature:
            query = query.where(model.feature_key == feature)
        if segment:
            query = query.where(model.segment == segment)
        return query

    def entries(
        self,
        kind: str,
        feature: str | None,
        segment: str | None,
        category: UUID | None,
        limit: int,
        cursor: UUID | None,
    ) -> Data:
        def read(_: Any) -> Data:
            model = FeatureInterest if kind == "interest" else FeedbackEntry
            query = self._query(model, feature, segment)
            if category is not None:
                query = (
                    query.where(FeedbackEntry.category_id == category)
                    if kind != "interest"
                    else query.where(False)
                )
            if cursor:
                query = query.where(model.id > cursor)
            rows = list(self.db.scalars(query.order_by(model.id).limit(limit + 1)))
            return {
                "items": [
                    FeedbackEntryRead.model_validate(row).model_dump(mode="json")
                    for row in rows[:limit]
                ],
                "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
            }

        return self.uow.read(read)

    def summary(self, feature: str | None, segment: str | None) -> Data:
        def read(_: Any) -> Data:
            def count(model: Any) -> int:
                return int(
                    self.db.scalar(
                        select(func.count()).select_from(
                            self._query(model, feature, segment).subquery()
                        )
                    )
                    or 0
                )

            def values(column: str) -> list[str]:
                return sorted(
                    {
                        value
                        for model in (FeedbackEntry, FeatureInterest)
                        for value in self.db.scalars(
                            select(getattr(model, column))
                            .where(model.scope_id == self.scope)
                            .distinct()
                        )
                    }
                )

            return FeedbackSummary(
                interest_count=count(FeatureInterest),
                feedback_count=count(FeedbackEntry),
                features=values("feature_key"),
                segments=values("segment"),
            ).model_dump(mode="json")

        return self.uow.read(read)
