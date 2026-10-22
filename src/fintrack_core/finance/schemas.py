from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StrictBool, StringConstraints, field_validator, model_validator

from fintrack_common.api import DTO
from fintrack_core.finance.domain import CURRENCIES, MAX_MINOR

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Minor = Annotated[int, Field(strict=True, ge=0, le=MAX_MINOR)]
PositiveMinor = Annotated[int, Field(strict=True, ge=1, le=MAX_MINOR)]
Version = Annotated[int, Field(strict=True, ge=1)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Currency = Literal["BDT", "USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "SGD", "AED"]
AccountKind = Literal[
    "checking",
    "savings",
    "credit",
    "investment",
    "retirement",
    "crypto",
    "property",
    "vehicle",
    "valuables",
    "loan",
    "mortgage",
    "other",
    "cash",
    "mfs",
    "dps",
]
Kind = Literal["income", "expense", "transfer"]
Direction = Literal["in", "out"]
Frequency = Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"]


class Expected(DTO):
    expected_version: Version


class Patch(Expected):
    @model_validator(mode="after")
    def reject_invalid_null(self) -> Self:
        nullable = {
            "category_id",
            "group_id",
            "debit_card_last4",
            "end_on",
            "account_id",
            "merchant_contains",
            "min_amount_minor",
            "max_amount_minor",
            "set_category_id",
            "set_merchant",
            "add_tag",
        }
        for field in self.model_fields_set:
            if field not in nullable and getattr(self, field) is None:
                raise ValueError("Field cannot be null")
        return self


class AccountCreate(DTO):
    name: Name
    kind: AccountKind = "cash"
    currency: Currency = "BDT"
    institution: Name = "Manual"
    is_asset: StrictBool = True
    balance_minor: Minor = 0
    debit_card_last4: Annotated[str, StringConstraints(pattern=r"^\d{4}$")] | None = None


class AccountEdit(Patch):
    name: Name | None = None
    institution: Name | None = None
    hidden: StrictBool | None = None
    debit_card_last4: Annotated[str, StringConstraints(pattern=r"^\d{4}$")] | None = None


class Record(DTO):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class AccountRead(AccountCreate, Record):
    hidden: bool
    archived: bool


class AccountBatch(DTO):
    items: Annotated[list[AccountCreate], Field(min_length=1, max_length=20)]


class ObservationCreate(Expected):
    amount_minor: Minor
    effective_on: date


class GroupCreate(DTO):
    name: Name
    color: Color = "#718096"


class GroupEdit(Patch):
    name: Name | None = None
    color: Color | None = None
    archived: StrictBool | None = None


class GroupRead(GroupCreate, Record):
    archived: bool


class CategoryCreate(GroupCreate):
    kind: Kind = "expense"
    group_id: UUID | None = None
    icon: Tag = "tag"


class CategoryEdit(Patch):
    name: Name | None = None
    color: Color | None = None
    group_id: UUID | None = None
    icon: Tag | None = None
    archived: StrictBool | None = None


class CategoryRead(CategoryCreate, Record):
    archived: bool


class Split(DTO):
    category_id: UUID
    amount_minor: PositiveMinor


class TransactionCreate(DTO):
    account_id: UUID
    amount_minor: PositiveMinor
    direction: Direction = "out"
    kind: Literal["income", "expense"] = "expense"
    merchant: Text
    booked_on: date
    category_id: UUID | None = None
    notes: Annotated[str, Field(max_length=2000)] = ""
    tags: Annotated[list[Tag], Field(max_length=20)] = []
    splits: Annotated[list[Split], Field(max_length=50)] = []
    reviewed: StrictBool = False
    pending: StrictBool = False


class TransactionEdit(Patch):
    amount_minor: PositiveMinor | None = None
    direction: Direction | None = None
    kind: Literal["income", "expense"] | None = None
    merchant: Text | None = None
    booked_on: date | None = None
    category_id: UUID | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None
    tags: Annotated[list[Tag], Field(max_length=20)] | None = None
    pending: StrictBool | None = None
    splits: Annotated[list[Split], Field(max_length=50)] | None = None


class TransactionRead(Record):
    account_id: UUID
    amount_minor: int
    currency: Currency
    direction: Direction
    kind: Kind
    merchant: str
    booked_on: date
    category_id: UUID | None
    notes: str
    tags: list[str]
    splits: list[Split]
    reviewed: bool
    pending: bool
    hidden: bool
    deleted: bool
    transfer_pair_id: UUID | None
    classification_source: str


class Review(Expected):
    reviewed: StrictBool = True


class ItemVersion(DTO):
    id: UUID
    expected_version: Version


class ReviewBatch(DTO):
    items: Annotated[list[ItemVersion], Field(min_length=1, max_length=100)]
    reviewed: StrictBool = True


class Visibility(Expected):
    hidden: StrictBool


class Lifecycle(Expected):
    paired_expected_version: Version | None = None


class Splits(Expected):
    splits: Annotated[list[Split], Field(max_length=50)]


class Transfer(DTO):
    from_account_id: UUID
    to_account_id: UUID
    from_expected_version: Version
    to_expected_version: Version
    amount_minor: PositiveMinor
    booked_on: date
    description: Text = "Manual transfer bookkeeping"


class RuleCreate(DTO):
    merchant_contains: Name | None = None
    min_amount_minor: Minor | None = None
    max_amount_minor: Minor | None = None
    account_id: UUID | None = None
    set_category_id: UUID | None = None
    set_merchant: Text | None = None
    add_tag: Tag | None = None


class RuleEdit(RuleCreate, Patch):
    archived: StrictBool | None = None


class RuleRead(RuleCreate, Record):
    archived: bool


class RuleApply(Expected):
    items: Annotated[list[ItemVersion], Field(min_length=1, max_length=100)]


class BudgetCreate(DTO):
    currency: Currency = "BDT"
    income_minor: Minor
    savings_minor: Minor
    lines: Annotated[dict[UUID, Minor], Field(max_length=100)]


class BudgetLine(Expected):
    currency: Currency = "BDT"
    category_id: UUID
    amount_minor: Minor
    apply_future: StrictBool = False


class Rollover(DTO):
    enabled: StrictBool
    categories: Annotated[list[UUID], Field(max_length=100)]
    start_month: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")]


class BudgetEdit(Patch):
    currency: Currency = "BDT"
    income_minor: Minor | None = None
    savings_minor: Minor | None = None
    rollover: Rollover | None = None
    archived: StrictBool | None = None


class RecurringCreate(DTO):
    account_id: UUID
    name: Text
    amount_minor: PositiveMinor
    direction: Direction = "out"
    frequency: Frequency = "monthly"
    next_on: date
    end_on: date | None = None
    stopped: StrictBool = False


class RecurringEdit(Patch):
    name: Text | None = None
    amount_minor: PositiveMinor | None = None
    frequency: Frequency | None = None
    next_on: date | None = None
    end_on: date | None = None
    stopped: StrictBool | None = None


class RecurringRead(RecurringCreate, Record):
    currency: Currency


class ProfileEdit(Patch):
    name: Name | None = None
    currency: Currency | None = None
    timezone: Annotated[str, Field(max_length=60)] | None = None
    onboarded: StrictBool | None = None
    goals: Annotated[list[Tag], Field(max_length=10)] | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError:
                raise ValueError("Unsupported timezone") from None
        return value


def currency_registry() -> list[dict[str, str | int]]:
    return [{"code": code, "minorUnitScale": scale} for code, scale in CURRENCIES.items()]


class PreferencesEdit(Patch):
    theme: Literal["light", "dark", "system"] | None = None
    push_alerts: StrictBool | None = None
    email_digest: StrictBool | None = None
    budget_alerts: StrictBool | None = None
    price_alerts: StrictBool | None = None
    large_txn_alerts: StrictBool | None = None
    blur_amounts_on_open: StrictBool | None = None


class ProfileRead(DTO):
    id: UUID
    version: int
    name: str
    currency: Currency
    timezone: str
    onboarded: bool
    goals: list[str]
    preferences: dict[str, str | bool]


class ObservationRead(Record):
    account_id: UUID
    amount_minor: int
    effective_on: date


class ObservationResult(DTO):
    account: AccountRead
    observation: ObservationRead


class BudgetVersion(DTO):
    from_month: str
    lines: dict[str, int]


class BudgetRead(Record):
    currency: Currency
    income_minor: int
    savings_minor: int
    versions: list[BudgetVersion]
    overrides: dict[str, dict[str, int]]
    rollover: Rollover
    archived: bool


class BudgetRow(DTO):
    category_id: str
    planned_minor: int
    rollover_minor: int
    spent_minor: int
    remaining_minor: int


class BudgetView(DTO):
    budget: BudgetRead
    month: str
    currency: Currency
    policy_version: str
    rows: list[BudgetRow]


class Cashflow(DTO):
    income_minor: int
    expense_minor: int
    net_minor: int
    by_category: dict[str, int]


class Summary(DTO):
    month: str
    currency: Currency
    policy_version: str
    cashflow: Cashflow
    assets_minor: int
    liabilities_minor: int
    net_worth_minor: int
    spendable_minor: int
    committed_minor: int
    liquid_net_minor: int
    computed_on: date
    balance_history_available: bool
    balance_basis: str


class WorkspaceSnapshot(DTO):
    profile: ProfileRead
    accounts: Annotated[list[AccountRead], Field(max_length=1000)]
    transactions: Annotated[list[TransactionRead], Field(max_length=10000)]
    categories: Annotated[list[CategoryRead], Field(max_length=1000)]
    groups: Annotated[list[GroupRead], Field(max_length=1000)]
    rules: Annotated[list[RuleRead], Field(max_length=1000)]
    recurring: Annotated[list[RecurringRead], Field(max_length=1000)]
    observations: Annotated[list[ObservationRead], Field(max_length=20000)]
