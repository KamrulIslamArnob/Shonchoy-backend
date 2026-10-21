from datetime import date

from fintrack_core.finance.domain import (
    CURRENCIES,
    MAX_MINOR,
    Data,
    month,
    require,
    shift_month,
    totals,
)
from fintrack_core.finance.ports import ReadRepositories


def visible_transactions(r: ReadRepositories, start: str, end: str, currency: str) -> list[Data]:
    accounts = r.accounts.list(limit=1001, filters={"currency": currency})
    require(len(accounts) <= 1000, "Account report limit exceeded.")
    allowed = {a["id"] for a in accounts if not a["hidden"]}
    rows = r.transactions.list(
        limit=10001, filters={"currency": currency, "booked_from": start, "booked_to": end}
    )
    require(len(rows) <= 10000, "Transaction report limit exceeded.")
    return [t for t in rows if t["account_id"] in allowed]


def summary(r: ReadRepositories, selected: str, currency: str) -> Data:
    month(selected)
    require(currency in CURRENCIES, "Unsupported currency.")
    accounts = r.accounts.list(limit=1001, filters={"currency": currency})
    require(len(accounts) <= 1000, "Account report limit exceeded.")
    rows = [
        t
        for t in visible_transactions(
            r, selected + "-01", shift_month(selected, 1) + "-01", currency
        )
        if t["booked_on"].startswith(selected)
    ]
    visible = [a for a in accounts if not a["hidden"] and not a["archived"]]
    assets = sum(a["balance_minor"] for a in visible if a["is_asset"])
    debt = sum(a["balance_minor"] for a in visible if not a["is_asset"])
    spendable = sum(
        a["balance_minor"] for a in visible if a["kind"] in {"cash", "checking", "savings", "mfs"}
    )
    committed = sum(a["balance_minor"] for a in visible if a["kind"] == "dps")
    require(
        all(
            abs(v) <= MAX_MINOR
            for v in [
                assets,
                debt,
                spendable,
                committed,
                assets - debt,
                spendable + committed - debt,
            ]
        ),
        "Aggregate balance exceeds JSON integer range.",
    )
    return {
        "month": selected,
        "currency": currency,
        "policy_version": "dev-v1",
        "cashflow": totals(rows),
        "assets_minor": assets,
        "liabilities_minor": debt,
        "net_worth_minor": assets - debt,
        "spendable_minor": spendable,
        "committed_minor": committed,
        "liquid_net_minor": spendable + committed - debt,
        "computed_on": date.today().isoformat(),
        "balance_history_available": False,
        "balance_basis": "observations; transaction edits do not alter observed balances",
    }
