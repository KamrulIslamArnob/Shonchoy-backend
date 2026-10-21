import ast
from datetime import date
from pathlib import Path

import pytest

from fintrack_core.finance.domain import (
    MAX_MINOR,
    DomainError,
    next_occurrence,
    totals,
    validate_transaction,
)


def record(**changes):
    return {
        "amount_minor": 100,
        "kind": "expense",
        "direction": "out",
        "hidden": False,
        "deleted": False,
        "pending": False,
        "splits": [],
        "category_id": "synthetic",
        **changes,
    }


def test_income_reversal_refund_and_split_counts_conserve_exactly():
    value = totals(
        [
            record(
                amount_minor=123,
                splits=[
                    {"category_id": "a", "amount_minor": 100},
                    {"category_id": "b", "amount_minor": 23},
                ],
            ),
            record(amount_minor=23, direction="in", category_id="b"),
            record(kind="income", direction="in", amount_minor=1000),
            record(kind="income", direction="out", amount_minor=50),
            record(kind="transfer", amount_minor=999),
            record(hidden=True),
            record(deleted=True),
            record(pending=True),
        ]
    )
    assert value == {
        "income_minor": 950,
        "expense_minor": 100,
        "net_minor": 850,
        "by_category": {"a": 100, "b": 0},
    }


@pytest.mark.parametrize("amount", [0, -1, 1.5, "100", True, MAX_MINOR + 1])
def test_invalid_financial_amounts_fail_at_domain_boundary(amount):
    with pytest.raises(DomainError):
        validate_transaction(record(amount_minor=amount))


def test_duplicate_split_categories_and_unsafe_aggregate_are_rejected():
    with pytest.raises(DomainError):
        validate_transaction(
            record(
                splits=[
                    {"category_id": "a", "amount_minor": 50},
                    {"category_id": "a", "amount_minor": 50},
                ]
            )
        )
    with pytest.raises(DomainError):
        totals([record(amount_minor=MAX_MINOR), record(amount_minor=MAX_MINOR)])


def test_leap_day_anchor_is_preserved_when_representable():
    assert next_occurrence(date(2024, 2, 29), "yearly", 29) == date(2025, 2, 28)
    assert next_occurrence(date(2027, 2, 28), "yearly", 29) == date(2028, 2, 29)


def test_domain_application_and_http_boundaries_have_no_direct_database_commands():
    root = Path(__file__).parents[1] / "src" / "fintrack_core" / "finance"
    for source in [root / "domain.py", root / "ports.py", *(root / "application").glob("*.py")]:
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("sqlalchemy", "fastapi", "fintrack_core.finance.persistence")
                )
    for source in (root / "transport").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"commit", "execute", "scalars", "flush"}
