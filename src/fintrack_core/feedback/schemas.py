from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictBool, StringConstraints

from fintrack_common.api import DTO

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,59}$")]
Source = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,119}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class FeedbackOrigin(DTO):
    feature_key: Key
    segment: Key
    source: Source


class FeedbackEntryCreate(FeedbackOrigin):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    category_id: UUID | None = None


class FeedbackCategoryCreate(DTO):
    name: Name
    feature_key: Key | None = None


class FeedbackCategoryEdit(DTO):
    name: Name
    archived: StrictBool


class FeedbackCategoryRead(DTO):
    id: UUID
    name: str
    feature_key: str
    archived: bool
    version: int


class FeedbackReceipt(DTO):
    id: UUID
    created_at: datetime


class FeedbackContext(DTO):
    interested: bool
    categories: list[FeedbackCategoryRead]


class FeedbackEntryRead(FeedbackOrigin, FeedbackReceipt):
    subject_ref: str
    message: str = ""
    category_id: UUID | None = None


class FeedbackSummary(DTO):
    interest_count: int
    feedback_count: int
    features: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
