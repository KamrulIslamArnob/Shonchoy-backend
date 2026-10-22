"""Pure finance policies, independent of HTTP, ORM and configuration."""

from calendar import monthrange
from datetime import date
from typing import Any

Data = dict[str, Any]
MAX_MINOR = 9_000_000_000_000_000
CURRENCIES = {
    "BDT": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "INR": 2,
    "CAD": 2,
    "AUD": 2,
    "JPY": 0,
    "SGD": 2,
    "AED": 2,
}
KINDS = {
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
}


class DomainError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail
        super().__init__(detail)


def require(condition: bool, detail: str, status: int = 422) -> None:
    if not condition:
        raise DomainError(status, detail)


def minor(value: int, *, positive: bool = False) -> int:
    require(type(value) is int and abs(value) <= MAX_MINOR, "Invalid integer minor amount.")
    require(value > 0 if positive else value >= 0, "Amount is outside the allowed range.")
    return value


def month(value: str) -> str:
    try:
        require(len(value) == 7, "Month must use YYYY-MM.")
        date.fromisoformat(value + "-01")
    except ValueError:
        raise DomainError(422, "Invalid calendar month.") from None
    return value


def shift_month(value: str, offset: int) -> str:
    year, mon = map(int, month(value).split("-"))
    total = year * 12 + mon - 1 + offset
    require(1 <= total // 12 <= 9999, "Calendar range is unsupported.")
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def validate_transaction(data: Data) -> None:
    minor(data["amount_minor"], positive=True)
    require(data["kind"] in {"income", "expense", "transfer"}, "Invalid transaction kind.")
    require(data["direction"] in {"in", "out"}, "Invalid direction.")
    splits = data.get("splits", [])
    if splits:
        require(data["kind"] != "transfer", "Transfers cannot have spending splits.")
        for part in splits:
            minor(part["amount_minor"], positive=True)
        require(len({s["category_id"] for s in splits}) == len(splits), "Duplicate split category.")
        require(
            sum(p["amount_minor"] for p in splits) == data["amount_minor"],
            "Split amounts must conserve the transaction amount.",
        )


def spending_parts(transaction: Data) -> list[tuple[str | None, int]]:
    if (
        transaction["hidden"]
        or transaction["deleted"]
        or transaction["pending"]
        or transaction["kind"] != "expense"
    ):
        return []
    sign = 1 if transaction["direction"] == "out" else -1
    return [(p["category_id"], sign * p["amount_minor"]) for p in transaction["splits"]] or [
        (transaction.get("category_id"), sign * transaction["amount_minor"])
    ]


def totals(transactions: list[Data]) -> Data:
    income = expense = 0
    categories: dict[str, int] = {}
    for item in transactions:
        if item["hidden"] or item["deleted"] or item["pending"]:
            continue
        if item["kind"] == "income":
            income += item["amount_minor"] * (1 if item["direction"] == "in" else -1)
        for category, amount in spending_parts(item):
            expense += amount
            key = category or "uncategorized"
            categories[key] = categories.get(key, 0) + amount
    require(
        all(abs(v) <= MAX_MINOR for v in [income, expense, income - expense, *categories.values()]),
        "Aggregated amount exceeds the supported JSON integer range.",
    )
    return {
        "income_minor": income,
        "expense_minor": expense,
        "net_minor": income - expense,
        "by_category": categories,
    }


def lines_for(budget: Data, selected: str) -> dict[str, int]:
    applicable = [v for v in budget["versions"] if v["from_month"] <= selected]
    lines = dict(max(applicable, key=lambda v: v["from_month"])["lines"]) if applicable else {}
    return {**lines, **budget["overrides"].get(selected, {})}


def next_occurrence(current: date, frequency: str, anchor_day: int | None = None) -> date:
    from datetime import timedelta

    if frequency in {"weekly", "biweekly"}:
        return current + timedelta(days=7 if frequency == "weekly" else 14)
    count = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency]
    target = shift_month(current.strftime("%Y-%m"), count)
    year, mon = map(int, target.split("-"))
    return date(year, mon, min(anchor_day or current.day, monthrange(year, mon)[1]))
