from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from fintrack_core.finance import models as m
from fintrack_core.finance.persistence import DEV_SCOPE, SqlUnitOfWork
from fintrack_core.models import Base


def setup_uow() -> tuple[SqlUnitOfWork, Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    uow = SqlUnitOfWork(db, "test-fingerprint-key", DEV_SCOPE)
    return uow, db


def test_deep_ledger_cashflow_and_balance_aggregation():
    uow, db = setup_uow()
    scope = DEV_SCOPE

    # Create checking, savings, credit, and DPS accounts
    checking_id, credit_id, dps_id = uuid4(), uuid4(), uuid4()
    cat_groceries, cat_dining = uuid4(), uuid4()

    db.add_all(
        [
            m.Workspace(id=scope, name="Ledger Test Workspace", currency="BDT"),
            m.Category(id=cat_groceries, scope_id=scope, name="Groceries", kind="expense"),
            m.Category(id=cat_dining, scope_id=scope, name="Dining", kind="expense"),
            m.Account(
                id=checking_id,
                scope_id=scope,
                name="Checking Account",
                kind="checking",
                currency="BDT",
                is_asset=True,
                balance_minor=50000,
            ),
            m.Account(
                id=credit_id,
                scope_id=scope,
                name="Credit Card",
                kind="credit",
                currency="BDT",
                is_asset=False,
                balance_minor=12000,
            ),
            m.Account(
                id=dps_id,
                scope_id=scope,
                name="DPS Savings",
                kind="dps",
                currency="BDT",
                is_asset=True,
                balance_minor=30000,
            ),
        ]
    )
    db.flush()

    # Add transactions: Income, simple expense, split expense, refund, pending, hidden
    db.add_all(
        [
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=100000,
                currency="BDT",
                kind="income",
                direction="in",
                merchant="Salary",
                booked_on=date(2026, 10, 5),
            ),
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=5000,
                currency="BDT",
                kind="expense",
                direction="out",
                merchant="Supermarket",
                booked_on=date(2026, 10, 10),
                category_id=cat_groceries,
            ),
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=8000,
                currency="BDT",
                kind="expense",
                direction="out",
                merchant="Department Store",
                booked_on=date(2026, 10, 15),
                splits=[
                    {"category_id": str(cat_groceries), "amount_minor": 5000},
                    {"category_id": str(cat_dining), "amount_minor": 3000},
                ],
            ),
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=1000,
                currency="BDT",
                kind="expense",
                direction="in",
                merchant="Groceries Refund",
                booked_on=date(2026, 10, 18),
                category_id=cat_groceries,
            ),
            # Pending transaction (should be excluded from cashflow)
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=9999,
                currency="BDT",
                kind="expense",
                direction="out",
                merchant="Pending Hold",
                booked_on=date(2026, 10, 20),
                pending=True,
            ),
            # Hidden transaction (should be excluded from cashflow)
            m.Transaction(
                scope_id=scope,
                account_id=checking_id,
                amount_minor=7777,
                currency="BDT",
                kind="expense",
                direction="out",
                merchant="Hidden Spend",
                booked_on=date(2026, 10, 21),
                hidden=True,
            ),
        ]
    )
    db.flush()

    # Query through the deep ledger interface
    def assert_ledger(r):
        cashflow = r.ledger.cashflow("2026-10", "BDT")
        # Income = 100000
        assert cashflow["income_minor"] == 100000
        # Expense: 5000 (groceries) + 8000 (splits) - 1000 (refund) = 12000
        assert cashflow["expense_minor"] == 12000
        assert cashflow["net_minor"] == 88000
        assert cashflow["by_category"] == {
            str(cat_groceries): 9000,  # 5000 + 5000 - 1000
            str(cat_dining): 3000,
        }

        # Balances
        balances = r.ledger.balances("BDT")
        assert balances["assets_minor"] == 80000  # 50000 (checking) + 30000 (dps)
        assert balances["liabilities_minor"] == 12000  # credit
        assert balances["spendable_minor"] == 50000  # checking
        assert balances["committed_minor"] == 30000  # dps
        assert balances["net_worth_minor"] == 68000  # 80000 - 12000
        assert balances["liquid_net_minor"] == 68000  # 50000 + 30000 - 12000

        # Full Summary
        summary = r.ledger.summary("2026-10", "BDT")
        assert summary["month"] == "2026-10"
        assert summary["currency"] == "BDT"
        assert summary["cashflow"] == cashflow
        assert summary["assets_minor"] == 80000
        assert summary["liabilities_minor"] == 12000

        return summary

    result = uow.read(assert_ledger)
    assert result["month"] == "2026-10"
    db.close()
