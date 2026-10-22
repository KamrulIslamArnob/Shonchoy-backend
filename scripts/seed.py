"""Comprehensive database seeder for FinTrack / Shonchoy.

Seeds realistic, fully loaded fake data into EVERY table in the database
covering 3 full months of activity (late July through late October 2026),
respecting all foreign key dependencies, concurrent logics, optimistic locking,
idempotency, outbox patterns, and rigorous database constraints and corner cases.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from fintrack_core.config import Settings
from fintrack_core.database import build_engine
from fintrack_core.finance import models as m
from fintrack_core.finance.persistence import DEV_SCOPE
from fintrack_core.models import Account as DevAccount
from fintrack_core.models import Transaction as DevTransaction

# Secondary workspace for multi-tenant isolation testing
SECONDARY_SCOPE = UUID("00000000-0000-4000-8000-000000000062")

# Fixed anchor date (local runtime date: 2026-10-21)
TODAY = date(2026, 10, 21)
START_DATE = date(2026, 7, 21)  # 3 full months back


# Deterministic pseudo-random generator
def deterministic_rng(seed: int = 1337):
    s = seed

    def rng():
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF

    return rng


rand = deterministic_rng(42)


def make_dt(d: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


def seed_database():
    settings = Settings()
    if not settings.database_url:
        print("ERROR: FINTRACK_DATABASE_URL is not set.")
        sys.exit(1)

    db_url = settings.database_url.get_secret_value()
    secret_key = (
        settings.dev_api_key.get_secret_value().encode()
        if settings.dev_api_key
        else b"dev-secret-key"
    )

    print("Connecting to Neon Postgres...")
    engine = build_engine(db_url)

    with Session(engine) as session:
        print("Starting atomic seeding transaction with foreign-key dependency order...")
        with session.begin():
            # ---------------------------------------------------------
            # STEP 0: Clean existing data in reverse dependency order
            # ---------------------------------------------------------
            print("1. Cleaning old records in reverse topological order...")
            session.execute(delete(m.Outbox))
            session.execute(delete(m.Audit))
            session.execute(delete(m.Idempotency))
            session.execute(delete(m.Transaction))
            session.execute(delete(m.Observation))
            session.execute(delete(m.Rule))
            session.execute(delete(m.Recurring))
            session.execute(delete(m.Budget))
            session.execute(delete(m.Account))
            session.execute(delete(m.Category))
            session.execute(delete(m.Group))
            session.execute(delete(m.Workspace))
            session.execute(delete(DevTransaction))
            session.execute(delete(DevAccount))
            session.flush()

            # ---------------------------------------------------------
            # STEP 1: Seed Workspaces (Root entity)
            # ---------------------------------------------------------
            print("2. Seeding core_workspaces (Primary user profile & secondary tenant)...")
            primary_ws = m.Workspace(
                id=DEV_SCOPE,
                version=10,
                name="ornoop",
                currency="BDT",
                timezone="Asia/Dhaka",
                onboarded=True,
                goals=["emergency_fund", "investing", "debt_payoff", "home_purchase"],
                preferences={
                    "theme": "dark",
                    "blur_amounts_on_open": False,
                    "push_alerts": True,
                    "email_digest": True,
                    "budget_alerts": True,
                    "price_alerts": True,
                    "large_txn_alerts": True,
                },
            )
            secondary_ws = m.Workspace(
                id=SECONDARY_SCOPE,
                version=1,
                name="Secondary Household",
                currency="BDT",
                timezone="Asia/Dhaka",
                onboarded=False,
                goals=["travel"],
                preferences={"theme": "light"},
            )
            session.add_all([primary_ws, secondary_ws])
            session.flush()

            # ---------------------------------------------------------
            # STEP 2: Seed Category Groups
            # ---------------------------------------------------------
            print("3. Seeding core_category_groups...")
            group_defs = [
                ("g_food", "Food & Drink", "#F2A65A", False),
                ("g_home", "Home & Bills", "#7C8CFF", False),
                ("g_move", "Getting Around", "#4FC1C9", False),
                ("g_life", "Lifestyle", "#E879A6", False),
                ("g_health", "Health", "#6CCB8B", False),
                ("g_income", "Income", "#2BB673", False),
                ("g_transfer", "Transfers", "#8E8E93", False),
                ("g_other", "Other", "#9AA0A6", False),
                ("g_archived", "Archived Projects", "#718096", True),  # Edge case: archived group
            ]
            groups: dict[str, m.Group] = {}
            for tag, name, color, archived in group_defs:
                g = m.Group(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    name=name,
                    color=color,
                    archived=archived,
                    created_at=make_dt(START_DATE, 9, 0),
                    updated_at=make_dt(START_DATE, 9, 0),
                )
                groups[tag] = g
                session.add(g)
            session.flush()

            # ---------------------------------------------------------
            # STEP 3: Seed Categories (linked to Groups or ungrouped)
            # ---------------------------------------------------------
            print("4. Seeding core_categories...")
            cat_defs = [
                # Food
                ("c_groceries", "Groceries", "expense", "g_food", "#F2A65A", "cart", False),
                ("c_restaurants", "Restaurants", "expense", "g_food", "#F28B5A", "utensils", False),
                ("c_coffee", "Coffee", "expense", "g_food", "#C98F5A", "coffee", False),
                # Home
                ("c_rent", "Rent", "expense", "g_home", "#7C8CFF", "home", False),
                ("c_utilities", "Utilities", "expense", "g_home", "#9AA8FF", "zap", False),
                ("c_phone", "Phone & Internet", "expense", "g_home", "#6A79F0", "wifi", False),
                ("c_insurance", "Insurance", "expense", "g_home", "#5865D6", "shield", False),
                # Move
                ("c_gas", "Gas & Fuel", "expense", "g_move", "#4FC1C9", "fuel", False),
                (
                    "c_rideshare",
                    "Rideshare & Transport",
                    "expense",
                    "g_move",
                    "#3AA6AE",
                    "car",
                    False,
                ),
                # Life
                ("c_shopping", "Shopping", "expense", "g_life", "#E879A6", "bag", False),
                ("c_entertainment", "Entertainment", "expense", "g_life", "#D667C9", "film", False),
                (
                    "c_subscriptions",
                    "Subscriptions",
                    "expense",
                    "g_life",
                    "#B86AE0",
                    "repeat",
                    False,
                ),
                ("c_travel", "Travel", "expense", "g_life", "#F06A8F", "plane", False),
                # Health
                ("c_fitness", "Fitness", "expense", "g_health", "#6CCB8B", "dumbbell", False),
                ("c_health", "Health & Pharmacy", "expense", "g_health", "#52B87A", "pill", False),
                (
                    "c_personal",
                    "Personal Care",
                    "expense",
                    "g_health",
                    "#A3D977",
                    "sparkles",
                    False,
                ),
                # Other
                ("c_gifts", "Gifts & Donations", "expense", "g_other", "#B0B6BC", "gift", False),
                ("c_other", "Everything Else", "expense", "g_other", "#9AA0A6", "circle", False),
                # Income
                ("c_salary", "Salary", "income", "g_income", "#2BB673", "briefcase", False),
                (
                    "c_freelance",
                    "Consulting & Freelance",
                    "income",
                    "g_income",
                    "#38A169",
                    "laptop",
                    False,
                ),
                (
                    "c_interest",
                    "Interest & Profit",
                    "income",
                    "g_income",
                    "#3FC98A",
                    "percent",
                    False,
                ),
                ("c_reimburse", "Reimbursement", "income", "g_income", "#62D6A0", "undo", False),
                ("c_otherincome", "Other Income", "income", "g_income", "#86E0B6", "plus", False),
                # Transfers
                ("c_transfer", "Transfer", "expense", "g_transfer", "#8E8E93", "swap", False),
                (
                    "c_ccpay",
                    "Credit Card Payment",
                    "expense",
                    "g_transfer",
                    "#8E8E93",
                    "card",
                    False,
                ),
                # Corner cases:
                (
                    "c_ungrouped",
                    "Emergency Cash Outflow",
                    "expense",
                    None,
                    "#E53E3E",
                    "alert-circle",
                    False,
                ),  # None group
                (
                    "c_archived",
                    "Deprecated Crypto Bet",
                    "expense",
                    "g_archived",
                    "#718096",
                    "archive",
                    True,
                ),  # Archived
            ]
            categories: dict[str, m.Category] = {}
            for tag, name, kind, group_tag, color, icon, archived in cat_defs:
                group_id = groups[group_tag].id if group_tag else None
                cat = m.Category(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    name=name,
                    kind=kind,
                    group_id=group_id,
                    color=color,
                    icon=icon,
                    archived=archived,
                    created_at=make_dt(START_DATE, 9, 30),
                    updated_at=make_dt(START_DATE, 9, 30),
                )
                categories[tag] = cat
                session.add(cat)
            session.flush()

            # ---------------------------------------------------------
            # STEP 4: Seed Accounts
            # ---------------------------------------------------------
            print("4. Seeding core_accounts...")
            account_defs = [
                (
                    "acc_chk",
                    "City Bank Salary A/C",
                    "checking",
                    "BDT",
                    "City Bank",
                    True,
                    12845000,
                    "4021",
                    False,
                    False,
                ),
                (
                    "acc_cc",
                    "City Bank Amex Platinum",
                    "credit",
                    "BDT",
                    "City Bank",
                    False,
                    1845000,
                    "3382",
                    False,
                    False,
                ),
                (
                    "acc_sav",
                    "BRAC Bank Savings",
                    "savings",
                    "BDT",
                    "BRAC Bank",
                    True,
                    4500000,
                    "7710",
                    False,
                    False,
                ),
                (
                    "acc_dps",
                    "BRAC Bank 5-Yr DPS",
                    "dps",
                    "BDT",
                    "BRAC Bank",
                    True,
                    6000000,
                    None,
                    False,
                    False,
                ),
                (
                    "acc_bkash",
                    "bKash Personal",
                    "mfs",
                    "BDT",
                    "bKash",
                    True,
                    850000,
                    None,
                    False,
                    False,
                ),
                (
                    "acc_nagad",
                    "Nagad Wallet",
                    "mfs",
                    "BDT",
                    "Nagad",
                    True,
                    320000,
                    None,
                    False,
                    False,
                ),
                (
                    "acc_cash",
                    "Cash in Hand",
                    "cash",
                    "BDT",
                    "Cash",
                    True,
                    450000,
                    None,
                    False,
                    False,
                ),
                (
                    "acc_fdr",
                    "Eastern Bank (EBL) FDR",
                    "investment",
                    "BDT",
                    "Eastern Bank (EBL)",
                    True,
                    50000000,
                    None,
                    False,
                    False,
                ),
                (
                    "acc_mort",
                    "DBBL Home Loan",
                    "mortgage",
                    "BDT",
                    "Dutch-Bangla Bank (DBBL)",
                    False,
                    245000000,
                    None,
                    False,
                    False,
                ),
                # Edge cases:
                (
                    "acc_zero",
                    "Zero Balance Reserve",
                    "savings",
                    "BDT",
                    "City Bank",
                    True,
                    0,
                    None,
                    False,
                    False,
                ),  # Balance 0
                (
                    "acc_usd",
                    "Emergency Vault USD",
                    "savings",
                    "USD",
                    "HSBC",
                    True,
                    250000,
                    None,
                    False,
                    False,
                ),  # USD currency
                (
                    "acc_hidden",
                    "Hidden Reserve Cash",
                    "cash",
                    "BDT",
                    "Cash",
                    True,
                    50000,
                    None,
                    True,
                    False,
                ),  # Hidden
                (
                    "acc_archived",
                    "Old Student Account",
                    "checking",
                    "BDT",
                    "Standard Chartered",
                    True,
                    0,
                    "9901",
                    False,
                    True,
                ),  # Archived
            ]
            accounts: dict[str, m.Account] = {}
            for (
                tag,
                name,
                kind,
                currency,
                inst,
                is_asset,
                bal,
                card,
                hidden,
                archived,
            ) in account_defs:
                acc = m.Account(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    name=name,
                    kind=kind,
                    currency=currency,
                    institution=inst,
                    is_asset=is_asset,
                    balance_minor=bal,
                    debit_card_last4=card,
                    hidden=hidden,
                    archived=archived,
                    created_at=make_dt(START_DATE, 10, 0),
                    updated_at=make_dt(START_DATE, 10, 0),
                )
                accounts[tag] = acc
                session.add(acc)
            session.flush()

            # ---------------------------------------------------------
            # STEP 5: Seed Balance Observations (Historical snapshots)
            # ---------------------------------------------------------
            print("5. Seeding core_balance_observations...")
            observation_dates = [
                date(2026, 7, 31),
                date(2026, 8, 31),
                date(2026, 9, 30),
                date(2026, 10, 15),
                TODAY,
            ]
            obs_counts = 0
            for obs_d in observation_dates:
                for _tag, acc in accounts.items():
                    if acc.archived:
                        continue
                    # Slightly fluctuating historical balance
                    factor = 0.88 + (obs_d - START_DATE).days * 0.0012
                    obs_amount = int(acc.balance_minor * factor)
                    obs = m.Observation(
                        id=uuid4(),
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=acc.id,
                        amount_minor=max(0, obs_amount),
                        effective_on=obs_d,
                        created_at=make_dt(obs_d, 23, 59),
                        updated_at=make_dt(obs_d, 23, 59),
                    )
                    session.add(obs)
                    obs_counts += 1
            session.flush()

            # ---------------------------------------------------------
            # STEP 6: Seed Rules
            # ---------------------------------------------------------
            print("6. Seeding core_rules...")
            rule_defs = [
                (
                    "SHWAPNO",
                    None,
                    None,
                    None,
                    categories["c_groceries"].id,
                    "Shwapno Superstore",
                    "groceries",
                    False,
                ),
                (
                    "UBER",
                    None,
                    None,
                    None,
                    categories["c_rideshare"].id,
                    "Uber Bangladesh",
                    "transport",
                    False,
                ),
                (
                    "PATHAO",
                    None,
                    None,
                    None,
                    categories["c_rideshare"].id,
                    "Pathao Ride",
                    "transport",
                    False,
                ),
                (
                    "NORTH END",
                    None,
                    None,
                    None,
                    categories["c_coffee"].id,
                    "North End Coffee Roasters",
                    "coffee",
                    False,
                ),
                (None, 1000000, None, None, None, None, "large-expense", False),  # Amount criterion
                (
                    None,
                    None,
                    None,
                    accounts["acc_bkash"].id,
                    None,
                    None,
                    "mfs",
                    False,
                ),  # Account criterion
                (
                    "OBSOLETE VENDOR",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "obsolete",
                    True,
                ),  # Archived rule edge case
            ]
            for m_cont, min_amt, max_amt, acc_id, set_cat_id, set_m, tag, arch in rule_defs:
                r_obj = m.Rule(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    merchant_contains=m_cont,
                    min_amount_minor=min_amt,
                    max_amount_minor=max_amt,
                    account_id=acc_id,
                    set_category_id=set_cat_id,
                    set_merchant=set_m,
                    add_tag=tag,
                    archived=arch,
                    created_at=make_dt(START_DATE, 11, 0),
                    updated_at=make_dt(START_DATE, 11, 0),
                )
                session.add(r_obj)
            session.flush()

            # ---------------------------------------------------------
            # STEP 7: Seed Budgets (with Versioning, Overrides, Rollover)
            # ---------------------------------------------------------
            print("7. Seeding core_budgets...")
            v1_lines = {
                str(categories["c_groceries"].id): 1800000,
                str(categories["c_restaurants"].id): 800000,
                str(categories["c_rent"].id): 3500000,
                str(categories["c_utilities"].id): 450000,
                str(categories["c_phone"].id): 250000,
                str(categories["c_gas"].id): 350000,
                str(categories["c_rideshare"].id): 450000,
                str(categories["c_shopping"].id): 1000000,
                str(categories["c_entertainment"].id): 500000,
                str(categories["c_subscriptions"].id): 250000,
                str(categories["c_health"].id): 400000,
            }
            v2_lines = {
                **v1_lines,
                str(categories["c_groceries"].id): 1900000,
                str(categories["c_shopping"].id): 800000,
            }
            b_obj = m.Budget(
                id=uuid4(),
                scope_id=DEV_SCOPE,
                version=3,
                currency="BDT",
                income_minor=15000000,
                savings_minor=4000000,
                versions=[
                    {"from_month": "2026-08", "lines": v1_lines},
                    {"from_month": "2026-10", "lines": v2_lines},
                ],
                overrides={
                    "2026-09": {
                        str(categories["c_shopping"].id): 1500000,
                        str(categories["c_gifts"].id): 600000,
                    }
                },
                rollover={
                    "enabled": True,
                    "categories": [
                        str(categories["c_groceries"].id),
                        str(categories["c_restaurants"].id),
                    ],
                    "start_month": "2026-08",
                },
                archived=False,
                created_at=make_dt(date(2026, 8, 1), 10, 0),
                updated_at=make_dt(TODAY, 10, 0),
            )
            session.add(b_obj)
            session.flush()

            # ---------------------------------------------------------
            # STEP 8: Seed Recurring Series
            # ---------------------------------------------------------
            print("8. Seeding core_recurring...")
            rec_defs = [
                (
                    "acc_chk",
                    "TechCorp Salary",
                    12500000,
                    "in",
                    "monthly",
                    date(2026, 10, 31),
                    None,
                    False,
                ),
                (
                    "acc_chk",
                    "Apartment Rent (Gulshan)",
                    3500000,
                    "out",
                    "monthly",
                    date(2026, 11, 1),
                    None,
                    False,
                ),
                (
                    "acc_chk",
                    "DPDC Electricity Bill",
                    380000,
                    "out",
                    "monthly",
                    date(2026, 11, 15),
                    None,
                    False,
                ),
                (
                    "acc_cc",
                    "Link3 Fiber Broadband",
                    150000,
                    "out",
                    "monthly",
                    date(2026, 11, 8),
                    None,
                    False,
                ),
                (
                    "acc_cc",
                    "Netflix Bangladesh",
                    120000,
                    "out",
                    "monthly",
                    date(2026, 11, 5),
                    None,
                    False,
                ),
                (
                    "acc_cc",
                    "Spotify Premium",
                    39900,
                    "out",
                    "monthly",
                    date(2026, 11, 12),
                    None,
                    False,
                ),
                (
                    "acc_cash",
                    "Weekly CNG Refuel",
                    85000,
                    "out",
                    "weekly",
                    date(2026, 10, 24),
                    None,
                    False,
                ),
                (
                    "acc_bkash",
                    "Bi-weekly Home Maintenance",
                    250000,
                    "out",
                    "biweekly",
                    date(2026, 10, 28),
                    None,
                    False,
                ),
                (
                    "acc_chk",
                    "Quarterly Vehicle Service",
                    800000,
                    "out",
                    "quarterly",
                    date(2026, 12, 10),
                    None,
                    False,
                ),
                (
                    "acc_cc",
                    "Annual Domain Renewal",
                    450000,
                    "out",
                    "yearly",
                    date(2027, 3, 15),
                    None,
                    False,
                ),
                # Edge cases:
                (
                    "acc_chk",
                    "Appliance EMI Installment",
                    420000,
                    "out",
                    "monthly",
                    date(2026, 11, 10),
                    date(2027, 2, 10),
                    False,
                ),  # End date
                (
                    "acc_cc",
                    "Cancelled Gym Membership",
                    300000,
                    "out",
                    "monthly",
                    date(2026, 9, 1),
                    date(2026, 9, 30),
                    True,
                ),  # Stopped
            ]
            for acc_tag, name, amt, direct, freq, next_d, end_d, stopped in rec_defs:
                rec_obj = m.Recurring(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    account_id=accounts[acc_tag].id,
                    name=name,
                    amount_minor=amt,
                    currency="BDT",
                    direction=direct,
                    frequency=freq,
                    next_on=next_d,
                    end_on=end_d,
                    stopped=stopped,
                    created_at=make_dt(START_DATE, 12, 0),
                    updated_at=make_dt(START_DATE, 12, 0),
                )
                session.add(rec_obj)
            session.flush()

            # ---------------------------------------------------------
            # STEP 9: Seed Transactions (3 Full Months: July 21 - Oct 21)
            # ---------------------------------------------------------
            print("9. Seeding core_transactions (3 full months of rich, dynamic transactions)...")
            tx_count = 0

            # Helper to insert a transaction
            def add_tx(
                acc_tag: str,
                amt_minor: int,
                kind: str,
                direction: str,
                merchant: str,
                booked_on: date,
                cat_tag: str | None = None,
                reviewed: bool = True,
                pending: bool = False,
                hidden: bool = False,
                deleted: bool = False,
                notes: str = "",
                tags: list[str] | None = None,
                splits: list[dict[str, Any]] | None = None,
                transfer_pair_id: UUID | None = None,
                classification_source: str = "manual",
            ) -> UUID:
                nonlocal tx_count
                tid = uuid4()
                cat_id = categories[cat_tag].id if cat_tag else None
                t_obj = m.Transaction(
                    id=tid,
                    scope_id=DEV_SCOPE,
                    version=1,
                    account_id=accounts[acc_tag].id,
                    amount_minor=amt_minor,
                    currency=accounts[acc_tag].currency,
                    kind=kind,
                    direction=direction,
                    merchant=merchant,
                    booked_on=booked_on,
                    category_id=cat_id,
                    reviewed=reviewed,
                    pending=pending,
                    hidden=hidden,
                    deleted=deleted,
                    notes=notes,
                    tags=tags or [],
                    splits=splits or [],
                    transfer_pair_id=transfer_pair_id,
                    classification_source=classification_source,
                    created_at=make_dt(booked_on, 14, 0),
                    updated_at=make_dt(booked_on, 14, 0),
                )
                session.add(t_obj)
                tx_count += 1
                return tid

            # --- A. Monthly Incomes ---
            salary_dates = [
                date(2026, 7, 31),
                date(2026, 8, 28),
                date(2026, 9, 25),
                date(2026, 10, 16),
            ]
            for s_date in salary_dates:
                add_tx(
                    "acc_chk",
                    12500000,
                    "income",
                    "in",
                    "TechCorp Salary",
                    s_date,
                    "c_salary",
                    tags=["salary", "sms", "city"],
                )

            # Freelance income
            add_tx(
                "acc_chk",
                4500000,
                "income",
                "in",
                "Upwork Escrow Freelance",
                date(2026, 8, 15),
                "c_freelance",
                tags=["freelance", "online"],
            )
            add_tx(
                "acc_chk",
                6000000,
                "income",
                "in",
                "FinTech Client Retainer",
                date(2026, 9, 18),
                "c_freelance",
                tags=["freelance", "wire"],
            )

            # DPS profit credits
            for m_day in [date(2026, 7, 28), date(2026, 8, 28), date(2026, 9, 28)]:
                add_tx(
                    "acc_dps",
                    285000,
                    "income",
                    "in",
                    "BRAC Bank DPS Profit",
                    m_day,
                    "c_interest",
                    tags=["interest"],
                )

            # --- B. Monthly Fixed Expenditures ---
            for m_str in ["2026-08", "2026-09", "2026-10"]:
                y, m_num = int(m_str[:4]), int(m_str[5:])
                # Rent on 1st
                add_tx(
                    "acc_chk",
                    3500000,
                    "expense",
                    "out",
                    "Apartment Rent (Gulshan)",
                    date(y, m_num, 1),
                    "c_rent",
                    notes="Monthly home rent",
                    tags=["rent"],
                )
                # Gym on 3rd
                add_tx(
                    "acc_cc",
                    300000,
                    "expense",
                    "out",
                    "Blade 68 Fitness Gym",
                    date(y, m_num, 3),
                    "c_fitness",
                    tags=["gym"],
                )
                # Link3 on 8th
                add_tx(
                    "acc_cc",
                    150000,
                    "expense",
                    "out",
                    "Link3 Fiber Broadband",
                    date(y, m_num, 8),
                    "c_phone",
                    tags=["utilities", "sms"],
                )
                # Spotify on 12th
                add_tx(
                    "acc_cc",
                    39900,
                    "expense",
                    "out",
                    "Spotify Premium",
                    date(y, m_num, 12),
                    "c_subscriptions",
                    tags=["streaming"],
                )
                # Netflix on 15th
                add_tx(
                    "acc_cc",
                    120000,
                    "expense",
                    "out",
                    "Netflix Bangladesh",
                    date(y, m_num, 15),
                    "c_subscriptions",
                    tags=["streaming"],
                )
                # DPDC Electricity on 16th
                elec_amt = 345000 if m_num == 8 else (412000 if m_num == 9 else 389000)
                add_tx(
                    "acc_chk",
                    elec_amt,
                    "expense",
                    "out",
                    "DPDC Electricity Bill",
                    date(y, m_num, 16),
                    "c_utilities",
                    tags=["bills"],
                )
                # GP Postpaid on 22nd
                add_tx(
                    "acc_cc",
                    120000,
                    "expense",
                    "out",
                    "Grameenphone Postpaid Bill",
                    date(y, m_num, 22),
                    "c_phone",
                    tags=["phone"],
                )

            # --- C. Transfers (Matched Pairs with mutual transfer_pair_id) ---
            # 1. Credit card settlements
            for pay_d, amt in [
                (date(2026, 8, 20), 1650000),
                (date(2026, 9, 20), 1820000),
                (date(2026, 10, 18), 1420000),
            ]:
                tid_out = uuid4()
                tid_in = uuid4()
                # Outflow from checking
                session.add(
                    m.Transaction(
                        id=tid_out,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_chk"].id,
                        amount_minor=amt,
                        currency="BDT",
                        kind="transfer",
                        direction="out",
                        merchant="Amex Credit Card Bill Payment",
                        booked_on=pay_d,
                        category_id=categories["c_ccpay"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="Credit card bill payoff",
                        tags=["transfer", "ccpay"],
                        splits=[],
                        transfer_pair_id=tid_in,
                        classification_source="manual",
                        created_at=make_dt(pay_d, 16, 0),
                        updated_at=make_dt(pay_d, 16, 0),
                    )
                )
                # Inflow to credit card
                session.add(
                    m.Transaction(
                        id=tid_in,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_cc"].id,
                        amount_minor=amt,
                        currency="BDT",
                        kind="transfer",
                        direction="in",
                        merchant="Payment Received - Thank You",
                        booked_on=pay_d,
                        category_id=categories["c_ccpay"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="Payment credited",
                        tags=["transfer", "ccpay"],
                        splits=[],
                        transfer_pair_id=tid_out,
                        classification_source="manual",
                        created_at=make_dt(pay_d, 16, 0),
                        updated_at=make_dt(pay_d, 16, 0),
                    )
                )
                tx_count += 2

            # 2. DPS savings sweeps (2nd of each month)
            for dps_d in [date(2026, 8, 2), date(2026, 9, 2), date(2026, 10, 2)]:
                tid_out = uuid4()
                tid_in = uuid4()
                session.add(
                    m.Transaction(
                        id=tid_out,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_chk"].id,
                        amount_minor=1000000,
                        currency="BDT",
                        kind="transfer",
                        direction="out",
                        merchant="DPS Monthly Auto-Debit",
                        booked_on=dps_d,
                        category_id=categories["c_transfer"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="Monthly DPS installment",
                        tags=["dps", "savings"],
                        splits=[],
                        transfer_pair_id=tid_in,
                        classification_source="manual",
                        created_at=make_dt(dps_d, 10, 0),
                        updated_at=make_dt(dps_d, 10, 0),
                    )
                )
                session.add(
                    m.Transaction(
                        id=tid_in,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_dps"].id,
                        amount_minor=1000000,
                        currency="BDT",
                        kind="transfer",
                        direction="in",
                        merchant="DPS Installment Credited",
                        booked_on=dps_d,
                        category_id=categories["c_transfer"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="DPS installment",
                        tags=["dps", "savings"],
                        splits=[],
                        transfer_pair_id=tid_out,
                        classification_source="manual",
                        created_at=make_dt(dps_d, 10, 0),
                        updated_at=make_dt(dps_d, 10, 0),
                    )
                )
                tx_count += 2

            # 3. Add Money to bKash
            for b_d in [date(2026, 8, 10), date(2026, 9, 12), date(2026, 10, 5)]:
                tid_out, tid_in = uuid4(), uuid4()
                session.add(
                    m.Transaction(
                        id=tid_out,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_chk"].id,
                        amount_minor=500000,
                        currency="BDT",
                        kind="transfer",
                        direction="out",
                        merchant="bKash Add Money from Bank",
                        booked_on=b_d,
                        category_id=categories["c_transfer"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="Wallet top-up",
                        tags=["mfs", "transfer"],
                        splits=[],
                        transfer_pair_id=tid_in,
                        classification_source="manual",
                        created_at=make_dt(b_d, 11, 0),
                        updated_at=make_dt(b_d, 11, 0),
                    )
                )
                session.add(
                    m.Transaction(
                        id=tid_in,
                        scope_id=DEV_SCOPE,
                        version=1,
                        account_id=accounts["acc_bkash"].id,
                        amount_minor=500000,
                        currency="BDT",
                        kind="transfer",
                        direction="in",
                        merchant="Deposit from City Bank",
                        booked_on=b_d,
                        category_id=categories["c_transfer"].id,
                        reviewed=True,
                        pending=False,
                        hidden=False,
                        deleted=False,
                        notes="Add money deposit",
                        tags=["mfs", "transfer"],
                        splits=[],
                        transfer_pair_id=tid_out,
                        classification_source="manual",
                        created_at=make_dt(b_d, 11, 0),
                        updated_at=make_dt(b_d, 11, 0),
                    )
                )
                tx_count += 2

            # --- D. Split Transactions (Edge case) ---
            # 1. Unimart grocery + personal care split
            add_tx(
                "acc_cc",
                580000,
                "expense",
                "out",
                "Unimart Gulshan",
                date(2026, 8, 14),
                "c_groceries",
                notes="Weekly family haul",
                tags=["split", "supermarket"],
                splits=[
                    {"category_id": str(categories["c_groceries"].id), "amount_minor": 410000},
                    {"category_id": str(categories["c_personal"].id), "amount_minor": 170000},
                ],
            )
            # 2. Aarong shopping + gifts split
            add_tx(
                "acc_cc",
                850000,
                "expense",
                "out",
                "Aarong Flagship Store",
                date(2026, 9, 10),
                "c_shopping",
                notes="Festival shopping and family gifts",
                tags=["split", "festive"],
                splits=[
                    {"category_id": str(categories["c_shopping"].id), "amount_minor": 550000},
                    {"category_id": str(categories["c_gifts"].id), "amount_minor": 300000},
                ],
            )
            # 3. Shwapno groceries + pharmacy split
            add_tx(
                "acc_cc",
                620000,
                "expense",
                "out",
                "Shwapno Banani",
                date(2026, 10, 8),
                "c_groceries",
                notes="Groceries and wellness items",
                tags=["split", "groceries"],
                splits=[
                    {"category_id": str(categories["c_groceries"].id), "amount_minor": 480000},
                    {"category_id": str(categories["c_health"].id), "amount_minor": 140000},
                ],
            )

            # --- E. Refunds / Credits (Edge case: direction='in', kind='expense') ---
            add_tx(
                "acc_cc",
                145000,
                "expense",
                "in",
                "Daraz Bangladesh Refund",
                date(2026, 8, 22),
                "c_shopping",
                notes="Returned defective router",
                tags=["refund"],
            )
            add_tx(
                "acc_bkash",
                28000,
                "expense",
                "in",
                "Pathao Fare Correction Credit",
                date(2026, 9, 14),
                "c_rideshare",
                notes="Disputed driver fare",
                tags=["refund"],
            )
            add_tx(
                "acc_cc",
                65000,
                "expense",
                "in",
                "Unimart Overcharge Refund",
                date(2026, 10, 12),
                "c_groceries",
                notes="Item returned at customer service",
                tags=["refund"],
            )

            # --- F. Income Clawback / Reversal (Edge case: direction='out', kind='income') ---
            add_tx(
                "acc_chk",
                350000,
                "income",
                "out",
                "TechCorp Tax Withholding Adjustment",
                date(2026, 8, 30),
                "c_salary",
                notes="Statutory deduction retroactive correction",
                tags=["tax"],
            )

            # --- G. Recent Pending Transactions (Edge case: pending=True) ---
            add_tx(
                "acc_cc",
                35000,
                "expense",
                "out",
                "North End Coffee Roasters",
                TODAY,
                "c_coffee",
                reviewed=False,
                pending=True,
                tags=["coffee"],
            )
            add_tx(
                "acc_bkash",
                28000,
                "expense",
                "out",
                "Pathao Ride",
                TODAY,
                "c_rideshare",
                reviewed=False,
                pending=True,
                tags=["transport"],
            )
            add_tx(
                "acc_cc",
                85000,
                "expense",
                "out",
                "Star Kabab & Restaurant",
                TODAY - timedelta(days=1),
                "c_restaurants",
                reviewed=False,
                pending=True,
                tags=["dining"],
            )

            # --- H. Unreviewed Recent Transactions (Edge case: reviewed=False) ---
            add_tx(
                "acc_bkash",
                45000,
                "expense",
                "out",
                "Lazz Pharma Dhanmondi",
                TODAY - timedelta(days=2),
                "c_health",
                reviewed=False,
                pending=False,
                tags=["health"],
            )
            add_tx(
                "acc_cash",
                12000,
                "expense",
                "out",
                "Bhai Bhai Grocery",
                TODAY - timedelta(days=3),
                "c_groceries",
                reviewed=False,
                pending=False,
                tags=["cash"],
            )
            add_tx(
                "acc_cc",
                185000,
                "expense",
                "out",
                "Takeout Burger Banani",
                TODAY - timedelta(days=4),
                "c_restaurants",
                reviewed=False,
                pending=False,
                tags=["dining"],
            )

            # --- I. Hidden & Soft-Deleted Transactions (Edge cases) ---
            add_tx(
                "acc_chk",
                1200000,
                "expense",
                "out",
                "Surprise Anniversary Jewelers",
                date(2026, 9, 28),
                "c_gifts",
                hidden=True,
                notes="Confidential anniversary gift",
                tags=["confidential"],
            )
            add_tx(
                "acc_cc",
                45000,
                "expense",
                "out",
                "Duplicate Terminal POS Charge",
                date(2026, 8, 19),
                "c_other",
                deleted=True,
                notes="Accidental duplicate charge reversed",
                tags=["deleted"],
            )

            # --- J. Uncategorized Transaction (Edge case: category_id=None) ---
            add_tx(
                "acc_cash",
                150000,
                "expense",
                "out",
                "Cash Miscellaneous Expenditure",
                date(2026, 10, 11),
                None,
                notes="Untracked manual cash spending",
                tags=["unclassified"],
            )

            # --- K. Extreme Amount Corner Cases ---
            add_tx(
                "acc_cc",
                100,
                "expense",
                "out",
                "Gateway 1-BDT Card Verification",
                date(2026, 9, 2),
                "c_other",
                notes="Card authentication micro-charge",
                tags=["verification"],
            )
            add_tx(
                "acc_chk",
                4200000,
                "expense",
                "out",
                "Square Hospitals Annual Executive Health Check",
                date(2026, 8, 5),
                "c_health",
                notes="Annual comprehensive physical screening",
                tags=["medical"],
            )

            # --- L. Realistic Daily Variable Living Expenses across the entire 90 days ---
            # Generate realistic daily life transactions
            vendors = [
                (
                    "acc_cc",
                    "Shwapno Banani #0412",
                    "c_groceries",
                    120000,
                    380000,
                    0.40,
                    ["groceries", "sms"],
                ),
                (
                    "acc_cc",
                    "Unimart Gulshan 88",
                    "c_groceries",
                    180000,
                    520000,
                    0.30,
                    ["groceries", "sms"],
                ),
                ("acc_cc", "Star Kabab Banani", "c_restaurants", 45000, 185000, 0.35, ["dining"]),
                ("acc_cc", "Kacchi Bhai Dhaka", "c_restaurants", 65000, 140000, 0.25, ["dining"]),
                ("acc_cc", "North End Coffee", "c_coffee", 28000, 65000, 0.50, ["coffee"]),
                ("acc_cc", "Bean There Café", "c_coffee", 25000, 48000, 0.30, ["coffee"]),
                ("acc_cash", "CNG Station Mohakhali", "c_gas", 35000, 95000, 0.25, ["fuel"]),
                (
                    "acc_bkash",
                    "Pathao Ride *Trip",
                    "c_rideshare",
                    14000,
                    48000,
                    0.60,
                    ["transport", "sms"],
                ),
                (
                    "acc_cc",
                    "Uber *Trip Dhaka",
                    "c_rideshare",
                    28000,
                    75000,
                    0.30,
                    ["transport", "sms"],
                ),
                (
                    "acc_cc",
                    "Daraz BD Online Marketplace",
                    "c_shopping",
                    45000,
                    280000,
                    0.25,
                    ["online", "shopping"],
                ),
                (
                    "acc_cc",
                    "Star Cineplex SKS Tower",
                    "c_entertainment",
                    80000,
                    160000,
                    0.15,
                    ["cinema"],
                ),
                ("acc_bkash", "Lazz Pharma Gulshan", "c_health", 25000, 165000, 0.20, ["health"]),
                (
                    "acc_bkash",
                    "Bata Shoe Gulshan",
                    "c_shopping",
                    120000,
                    450000,
                    0.10,
                    ["shopping"],
                ),
                ("acc_cash", "Batighar Bookshop Dhaka", "c_other", 35000, 150000, 0.12, ["books"]),
            ]

            curr_d = START_DATE
            while curr_d <= TODAY - timedelta(days=2):
                for acc_tag, merch, c_tag, min_amt, max_amt, prob, tx_tags in vendors:
                    if rand() < prob:
                        amt = int(min_amt + rand() * (max_amt - min_amt))
                        add_tx(acc_tag, amt, "expense", "out", merch, curr_d, c_tag, tags=tx_tags)
                curr_d += timedelta(days=1)

            session.flush()

            # ---------------------------------------------------------
            # STEP 10: Seed Audit Events & Outbox (Event-driven Architecture)
            # ---------------------------------------------------------
            print("10. Seeding core_audit_events and core_outbox...")
            audit_events = [
                ("workspace.bootstrap", "bootstrap-init-2026-07-21", "delivered"),
                ("accounts.seed", "accounts-init-2026-07-21", "delivered"),
                ("catalog.seed", "catalog-init-2026-07-21", "delivered"),
                ("budgets.create:2026-08", "budget-v1-2026-08-01", "delivered"),
                ("rules.create", "rules-init-2026-08-02", "delivered"),
                ("transactions.monthly_salary:2026-08", "salary-aug-2026", "delivered"),
                ("budgets.override:2026-09", "budget-override-festive", "delivered"),
                ("budgets.upgrade:2026-10", "budget-v2-upgrade", "published"),
                ("transactions.recent_sync", "recent-sync-2026-10-21", "pending"),
            ]
            for op, cmd_key, outbox_status in audit_events:
                ev_id = uuid4()
                audit_row = m.Audit(
                    id=ev_id,
                    scope_id=DEV_SCOPE,
                    version=1,
                    operation=op,
                    command_key=cmd_key,
                    created_at=make_dt(TODAY - timedelta(days=1), 12, 0),
                    updated_at=make_dt(TODAY - timedelta(days=1), 12, 0),
                )
                session.add(audit_row)
                session.flush()

                outbox_row = m.Outbox(
                    id=uuid4(),
                    scope_id=DEV_SCOPE,
                    version=1,
                    event_id=ev_id,
                    event_type=op,
                    status=outbox_status,
                    created_at=make_dt(TODAY - timedelta(days=1), 12, 0),
                    updated_at=make_dt(TODAY - timedelta(days=1), 12, 0),
                )
                session.add(outbox_row)
            session.flush()

            # ---------------------------------------------------------
            # STEP 11: Seed Idempotency Log (Concurrency & Idempotency)
            # ---------------------------------------------------------
            print("11. Seeding core_idempotency...")
            idempotent_actions = [
                (
                    "cmd-ws-profile-001",
                    "profile.update",
                    {"name": "ornoop", "timezone": "Asia/Dhaka"},
                    {"status": 200, "updated": True},
                ),
                (
                    "cmd-ws-prefs-002",
                    "profile.preferences",
                    {"theme": "dark", "push_alerts": True},
                    {"status": 200, "updated": True},
                ),
                (
                    "cmd-budget-create-003",
                    "budgets.create:2026-08",
                    {"currency": "BDT", "income_minor": 15000000},
                    {"status": 201, "created": True},
                ),
                (
                    "cmd-transfer-settle-004",
                    "transfer.create",
                    {"from": "acc_chk", "to": "acc_cc", "amount": 1420000},
                    {"status": 201, "paired": True},
                ),
            ]
            for ikey, iop, ipayload, ires in idempotent_actions:
                encoded = json.dumps(ipayload, sort_keys=True, separators=(",", ":")).encode()
                fprint = hmac.new(
                    secret_key, b"finance-command-v1:" + encoded, hashlib.sha256
                ).hexdigest()
                idem_row = m.Idempotency(
                    scope_id=DEV_SCOPE,
                    key=ikey,
                    operation=iop,
                    fingerprint=fprint,
                    result=ires,
                )
                session.add(idem_row)
            session.flush()

            # ---------------------------------------------------------
            # STEP 12: Seed Legacy Development Tables (dev_accounts & dev_transactions)
            # ---------------------------------------------------------
            print("12. Seeding dev_accounts and dev_transactions...")
            dev_acc1 = DevAccount(
                id=uuid4(),
                name="Dev Primary Checking",
                currency="BDT",
                created_at=make_dt(START_DATE, 8, 0),
            )
            dev_acc2 = DevAccount(
                id=uuid4(),
                name="Dev High Yield Savings",
                currency="BDT",
                created_at=make_dt(START_DATE, 8, 0),
            )
            dev_acc3 = DevAccount(
                id=uuid4(),
                name="Dev Emergency Fund",
                currency="BDT",
                created_at=make_dt(START_DATE, 8, 0),
            )
            session.add_all([dev_acc1, dev_acc2, dev_acc3])
            session.flush()

            dev_tx_defs = [
                (dev_acc1.id, 12500000, "TechCorp Dev Salary", date(2026, 7, 31)),
                (dev_acc1.id, -3500000, "Rent Payment", date(2026, 8, 1)),
                (dev_acc1.id, -240000, "Electricity Bill", date(2026, 8, 15)),
                (dev_acc1.id, 12500000, "TechCorp Dev Salary", date(2026, 8, 28)),
                (dev_acc1.id, -3500000, "Rent Payment", date(2026, 9, 1)),
                (dev_acc1.id, -480000, "Supermarket Run", date(2026, 9, 12)),
                (dev_acc1.id, 12500000, "TechCorp Dev Salary", date(2026, 9, 25)),
                (dev_acc1.id, -3500000, "Rent Payment", date(2026, 10, 1)),
                (dev_acc1.id, -150000, "Broadband Internet", date(2026, 10, 8)),
                (dev_acc1.id, 12500000, "TechCorp Dev Salary", date(2026, 10, 16)),
                (dev_acc2.id, 5000000, "DPS Savings Transfer", date(2026, 8, 2)),
                (dev_acc2.id, 5000000, "DPS Savings Transfer", date(2026, 9, 2)),
                (dev_acc2.id, 5000000, "DPS Savings Transfer", date(2026, 10, 2)),
                (dev_acc2.id, 285000, "DPS Profit Credited", date(2026, 9, 28)),
                (dev_acc3.id, 2500000, "Emergency Reserve Topup", date(2026, 8, 10)),
                (dev_acc3.id, -500000, "Urgent Home Repair", date(2026, 9, 19)),
            ]
            for da_id, damt, ddesc, dbooked in dev_tx_defs:
                dtx = DevTransaction(
                    id=uuid4(),
                    account_id=da_id,
                    amount_minor=damt,
                    description=ddesc,
                    booked_on=dbooked,
                    created_at=make_dt(dbooked, 12, 0),
                )
                session.add(dtx)
            session.flush()

    print("\nSUCCESS: All 14 data tables seeded successfully!")


if __name__ == "__main__":
    seed_database()
