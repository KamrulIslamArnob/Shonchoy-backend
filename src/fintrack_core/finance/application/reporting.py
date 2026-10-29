"""Application-level reporting facade; delegates analytical queries to the deep Ledger module."""

from fintrack_core.finance.domain import CURRENCIES, Data, month, require
from fintrack_core.finance.ports import ReadRepositories


def visible_transactions(r: ReadRepositories, start: str, end: str, currency: str) -> list[Data]:
    return r.ledger.visible_transactions(start, end, currency)


def summary(r: ReadRepositories, selected: str, currency: str) -> Data:
    month(selected)
    require(currency in CURRENCIES, "Unsupported currency.")
    return r.ledger.summary(selected, currency)
