"""Additive synthetic scenarios for the server-owned development workspace only."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m
from fintrack_core.finance.persistence import DEV_SCOPE

START = date(2024, 1, 1)
LABEL = "scenario-v1"


def identifier(key: str, scope: UUID = DEV_SCOPE) -> UUID:
    return uuid5(NAMESPACE_URL, f"shonchoy/{LABEL}/{scope}/{key}")


def seed_scenarios(db: Session, as_of: date, scope: UUID = DEV_SCOPE) -> dict[str, int]:
    """Insert missing fixture IDs; never replace user records or reset tables."""
    if as_of < START or as_of > date(2030, 12, 31):
        raise ValueError("Scenario date must be between 2024 and 2030.")
    if db.get(m.Workspace, scope) is None:
        raise ValueError("Initialize the existing development workspace first.")
    stamp = datetime.combine(START, datetime.min.time(), UTC)
    counts: dict[str, int] = {}

    def row(model: Any, key: str, **values: Any) -> Any:
        return model(
            id=identifier(key, scope),
            scope_id=scope,
            version=1,
            created_at=stamp,
            updated_at=stamp,
            **values,
        )

    def insert(model: Any, rows: list[Any]) -> None:
        existing = set(db.scalars(select(model.id).where(model.scope_id == scope)))
        missing = [item for item in rows if item.id not in existing]
        db.add_all(missing)
        db.flush()
        counts[model.__tablename__] = len(missing)

    groups = {g.name: g for g in db.scalars(select(m.Group).where(m.Group.scope_id == scope))}
    definitions = [
        ("Groceries", "Food & Drink", "expense", "cart"),
        ("Restaurants", "Food & Drink", "expense", "utensils"),
        ("Coffee & Snacks", "Food & Drink", "expense", "coffee"),
        ("Rent", "Home & Bills", "expense", "home"),
        ("Utilities", "Home & Bills", "expense", "bolt"),
        ("Internet & Phone", "Home & Bills", "expense", "wifi"),
        ("Transport", "Getting Around", "expense", "car"),
        ("Shopping", "Lifestyle", "expense", "bag"),
        ("Entertainment", "Lifestyle", "expense", "film"),
        ("Subscriptions", "Lifestyle", "expense", "repeat"),
        ("Travel", "Lifestyle", "expense", "plane"),
        ("Fitness", "Health", "expense", "dumbbell"),
        ("Health & Pharmacy", "Health", "expense", "pill"),
        ("Personal Care", "Health", "expense", "sparkles"),
        ("Gifts & Donations", "Other", "expense", "gift"),
        ("Everything Else", "Other", "expense", "circle"),
        ("Salary", "Income", "income", "briefcase"),
        ("Consulting & Freelance", "Income", "income", "laptop"),
        ("Interest & Dividends", "Income", "income", "trending-up"),
        ("Transfers", "Transfers", "transfer", "repeat"),
    ]
    new_groups = []
    for _, group, _, _ in definitions:
        if group not in groups:
            groups[group] = row(
                m.Group, f"group/{group}", name=group, color="#718096", archived=False
            )
            new_groups.append(groups[group])
    insert(m.Group, new_groups)
    categories = {
        (c.name, c.kind): c
        for c in db.scalars(
            select(m.Category).where(m.Category.scope_id == scope, m.Category.archived.is_(False))
        )
    }
    new_categories = []
    for name, group, kind, icon in definitions:
        if (name, kind) not in categories:
            categories[name, kind] = row(
                m.Category,
                f"category/{name}/{kind}",
                name=name,
                kind=kind,
                group_id=groups[group].id,
                color="#2BB673" if kind == "income" else "#718096",
                icon=icon,
                archived=False,
            )
            new_categories.append(categories[name, kind])
    insert(m.Category, new_categories)

    # Amounts are integer paisa. Observed valuations are separate from cash-flow bookkeeping.
    account_defs = [
        ("checking", "Daily banking", 145_250_75, True, "City Bank"),
        ("savings", "Emergency fund", 350_000_00, True, "BRAC Bank"),
        ("cash", "Cash wallet", 12_345_67, True, "Manual"),
        ("mfs", "bKash wallet", 25_000_50, True, "bKash"),
        ("dps", "Monthly savings", 180_000_00, True, "Dutch-Bangla Bank"),
        ("investment", "Investment portfolio", 650_000_00, True, "Manual"),
        ("retirement", "Retirement fund", 900_000_00, True, "Manual"),
        ("crypto", "Volatile digital assets", 35_000_25, True, "Manual"),
        ("property", "Apartment valuation", 5_500_000_00, True, "Manual"),
        ("vehicle", "Vehicle valuation", 850_000_00, True, "Manual"),
        ("valuables", "Gold and valuables", 225_000_00, True, "Manual"),
        ("other", "Other receivable", 65_000_00, True, "Manual"),
        ("credit", "Credit card", 45_678_90, False, "City Bank"),
        ("loan", "Personal loan", 275_000_00, False, "BRAC Bank"),
        ("mortgage", "Home mortgage", 1_250_000_00, False, "Manual"),
        ("cash", "Zero balance", 0, True, "Manual"),
    ]
    accounts = [
        row(
            m.Account,
            f"account/{name}",
            name=f"[Demo] {name}",
            kind=kind,
            currency="BDT",
            institution=institution,
            is_asset=asset,
            balance_minor=balance,
            hidden=False,
            archived=False,
            debit_card_last4="4242" if kind == "checking" else None,
        )
        for kind, name, balance, asset, institution in account_defs
    ]
    accounts.extend(
        [
            row(
                m.Account,
                "account/hidden",
                name="[Demo] Hidden reserve",
                kind="savings",
                currency="BDT",
                institution="Manual",
                is_asset=True,
                balance_minor=900_000_00,
                hidden=True,
                archived=False,
            ),
            row(
                m.Account,
                "account/archived",
                name="[Demo] Archived wallet",
                kind="cash",
                currency="BDT",
                institution="Manual",
                is_asset=True,
                balance_minor=0,
                hidden=False,
                archived=True,
            ),
            row(
                m.Account,
                "account/usd",
                name="[Demo] USD wallet",
                kind="cash",
                currency="USD",
                institution="Manual",
                is_asset=True,
                balance_minor=125_050,
                hidden=False,
                archived=False,
            ),
        ]
    )
    insert(m.Account, accounts)
    span = max(1, (as_of - START).days)
    observations = []
    for day_index in range(span + 1):
        day = START + timedelta(days=day_index)
        for index, account in enumerate(accounts[:16]):
            if index != 0 and day_index % 7 and day != as_of:
                continue
            if account.is_asset:
                factor = 30 + 70 * day_index // span + ((day.month % 6) - 3) * 3
                if account.kind in {"investment", "crypto"} and day.month in {3, 9}:
                    factor = factor * 55 // 100
            else:
                factor = 100 + 1400 * (span - day_index) // span
            amount = (
                account.balance_minor
                if day == as_of
                else account.balance_minor * max(0, factor) // 100
            )
            observations.append(
                row(
                    m.Observation,
                    f"observation/{account.id}/{day}",
                    account_id=account.id,
                    amount_minor=amount,
                    effective_on=day,
                )
            )
    insert(m.Observation, observations)

    transactions: list[m.Transaction] = []

    def tx(
        key: str,
        day: date,
        amount: int,
        name: str,
        category: str | None,
        kind: str = "expense",
        direction: str = "out",
        account: m.Account | None = None,
        **flags: Any,
    ) -> None:
        cat = categories.get((category, kind)) if category else None
        transactions.append(
            row(
                m.Transaction,
                f"transaction/{key}",
                account_id=(account or accounts[0]).id,
                amount_minor=amount,
                currency=(account or accounts[0]).currency,
                kind=kind,
                direction=direction,
                merchant=f"[Demo] {name}",
                booked_on=day,
                category_id=cat.id if cat else None,
                reviewed=flags.pop("reviewed", True),
                pending=flags.pop("pending", False),
                hidden=flags.pop("hidden", False),
                deleted=flags.pop("deleted", False),
                notes="Synthetic scenario data",
                tags=["synthetic", LABEL],
                splits=flags.pop("splits", []),
                transfer_pair_id=flags.pop("transfer_pair_id", None),
                classification_source="manual",
            )
        )

    expense_names = [d[0] for d in definitions if d[2] == "expense"]
    for day_index in range(span + 1):
        day = START + timedelta(days=day_index)
        # Deliberate zero-activity month and quiet days; balances are still observed.
        if day.strftime("%Y-%m") == "2024-07":
            continue
        if day.weekday() != 6:
            category = expense_names[day_index % len(expense_names)]
            tx(
                f"daily/{day}",
                day,
                12_500 + (day_index * 7919) % 140_000,
                f"{category} purchase",
                category,
                account=accounts[day_index % 4],
            )
        if day.day == 1:
            tx(
                f"salary/{day}",
                day,
                160_000_00 + (day.year - 2024) * 15_000_00,
                "Monthly salary",
                "Salary",
                "income",
                "in",
            )
            tx(f"rent/{day}", day, 32_000_00, "Apartment rent", "Rent")
        if day.day == 15:
            tx(
                f"freelance/{day}",
                day,
                25_000_00 + day.month * 500_00,
                "Freelance project",
                "Consulting & Freelance",
                "income",
                "in",
            )
        if day.day == 20:
            for index, category in enumerate(expense_names):
                tx(
                    f"category/{day}/{index}",
                    day,
                    50_000 + index * 12_345,
                    f"{category} monthly bill",
                    category,
                )
        if day.day == 25 and day.month % 3 == 0:
            tx(f"spike/{day}", day, 450_000_00, "Large planned purchase", "Shopping")
        if day.day == 10:
            pair = identifier(f"transfer/{day}", scope)
            tx(
                f"transfer-out/{day}",
                day,
                8_000_00,
                "Savings transfer",
                "Transfers",
                "transfer",
                "out",
                transfer_pair_id=pair,
            )
            tx(
                f"transfer-in/{day}",
                day,
                8_000_00,
                "Savings transfer",
                "Transfers",
                "transfer",
                "in",
                account=accounts[1],
                transfer_pair_id=pair,
            )
        if day.day == 12:
            tx(f"refund/{day}", day, 1_250_50, "Returned purchase", "Shopping", direction="in")
        if day.day == 18:
            tx(f"reversal/{day}", day, 500_00, "Income correction", "Salary", "income", "out")

    grocery = str(categories["Groceries", "expense"].id)
    shopping = str(categories["Shopping", "expense"].id)
    for index, flags in enumerate(
        [
            {"pending": True, "reviewed": False},
            {"hidden": True},
            {"deleted": True},
            {"reviewed": False},
            {},
        ]
    ):
        tx(
            f"edge/{index}/{as_of}",
            as_of,
            1 if index == 4 else 12_345,
            [
                "Pending purchase",
                "Hidden purchase",
                "Deleted duplicate",
                "Needs review",
                "One paisa",
            ][index],
            "Groceries",
            **cast(dict[str, Any], flags),
        )
    tx(f"uncategorized/{as_of}", as_of, 5_000, "Uncategorized purchase", None, reviewed=False)
    tx(
        f"split/{as_of}",
        as_of,
        123_456,
        "Split department-store receipt",
        "Shopping",
        splits=[
            {"category_id": grocery, "amount_minor": 23_456},
            {"category_id": shopping, "amount_minor": 100_000},
        ],
    )
    tx(
        f"future/{as_of}",
        as_of + timedelta(days=10),
        8_000_00,
        "Future dated purchase",
        "Travel",
        pending=True,
        reviewed=False,
    )
    tx(f"usd/{as_of}", as_of, 1999, "Foreign currency purchase", None, account=accounts[-1])
    insert(m.Transaction, transactions)

    lines = {
        str(categories[name, "expense"].id): (2_000_00 if index % 3 else 10_000_00)
        for index, name in enumerate(expense_names)
    }
    budget = db.scalar(
        select(m.Budget).where(m.Budget.scope_id == scope, m.Budget.currency == "BDT")
    )
    if budget is None:
        insert(
            m.Budget,
            [
                row(
                    m.Budget,
                    "budget/BDT",
                    currency="BDT",
                    income_minor=200_000_00,
                    savings_minor=25_000_00,
                    versions=[{"from_month": "2024-01", "lines": lines}],
                    overrides={as_of.strftime("%Y-%m"): {shopping: 5_000_00}},
                    rollover={"enabled": True, "categories": [grocery], "start_month": "2024-01"},
                    archived=False,
                )
            ],
        )
    else:
        # Fill only the historical gap, leaving every existing/current allocation intact.
        versions = list(budget.versions)
        if not any(v["from_month"] <= "2024-01" for v in versions):
            versions.insert(0, {"from_month": "2024-01", "lines": lines})
            result = db.execute(
                update(m.Budget)
                .where(
                    m.Budget.id == budget.id,
                    m.Budget.scope_id == scope,
                    m.Budget.version == budget.version,
                )
                .values(versions=versions, version=budget.version + 1)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise ValueError("Budget changed concurrently; retry the complete seed.")
            counts["budget_history_backfill"] = 1

    recurring = []
    for index, frequency in enumerate(["weekly", "biweekly", "monthly", "quarterly", "yearly"]):
        recurring.append(
            row(
                m.Recurring,
                f"recurring/{frequency}",
                account_id=accounts[0].id,
                name=f"[Demo] {frequency.title()} membership",
                amount_minor=39_900 + index * 10_000,
                currency="BDT",
                direction="out",
                frequency=frequency,
                next_on=as_of + timedelta(days=index + 1),
                end_on=None,
                stopped=False,
            )
        )
    recurring.append(
        row(
            m.Recurring,
            "recurring/stopped",
            account_id=accounts[0].id,
            name="[Demo] Stopped subscription",
            amount_minor=99_900,
            currency="BDT",
            direction="out",
            frequency="monthly",
            next_on=as_of,
            end_on=as_of - timedelta(days=1),
            stopped=True,
        )
    )
    insert(m.Recurring, recurring)
    insert(
        m.Rule,
        [
            row(
                m.Rule,
                "rule/groceries",
                merchant_contains="Groceries purchase",
                min_amount_minor=None,
                max_amount_minor=None,
                account_id=accounts[0].id,
                set_category_id=UUID(grocery),
                set_merchant=None,
                add_tag="synthetic",
                archived=False,
            )
        ],
    )
    return counts
