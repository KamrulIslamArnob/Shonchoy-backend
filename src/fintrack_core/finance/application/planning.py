from datetime import date

from fintrack_core.finance.application.catalog import validate_category
from fintrack_core.finance.application.reporting import visible_transactions
from fintrack_core.finance.domain import (
    CURRENCIES,
    Data,
    lines_for,
    minor,
    month,
    next_occurrence,
    require,
    shift_month,
    totals,
)
from fintrack_core.finance.ports import ReadRepositories, Repositories


def budget_for(r: ReadRepositories, currency: str) -> Data:
    rows = r.budgets.list(limit=1, filters={"currency": currency})
    require(bool(rows), "Budget not found.", 404)
    return rows[0]


def check_lines(r: ReadRepositories, lines: dict[str, int]) -> None:
    for category, amount in lines.items():
        validate_category(r, category, "expense")
        minor(amount)


def create_budget(r: Repositories, selected: str, data: Data) -> Data:
    month(selected)
    require(data["currency"] in CURRENCIES, "Unsupported currency.")
    require(
        not r.budgets.list(limit=1, filters={"currency": data["currency"]}),
        "A budget already exists for this currency; edit its version instead.",
        409,
    )
    minor(data["income_minor"])
    minor(data["savings_minor"])
    require(data["savings_minor"] <= data["income_minor"], "Savings target exceeds income.")
    check_lines(r, data["lines"])
    return r.budgets.add(
        {
            "currency": data["currency"],
            "income_minor": data["income_minor"],
            "savings_minor": data["savings_minor"],
            "versions": [{"from_month": selected, "lines": data["lines"]}],
            "overrides": {},
            "rollover": {"enabled": False, "categories": [], "start_month": selected},
        }
    )


def line(r: Repositories, selected: str, data: Data) -> Data:
    month(selected)
    budget = budget_for(r, data["currency"])
    require(not budget["archived"], "Budget is archived.", 409)
    check_lines(r, {data["category_id"]: data["amount_minor"]})
    versions, overrides = list(budget["versions"]), dict(budget["overrides"])
    category = data["category_id"]
    require(selected >= min(v["from_month"] for v in versions), "Month predates this budget.")
    if data["apply_future"]:
        base = lines_for({**budget, "overrides": {}}, selected)
        versions = (
            [v for v in versions if v["from_month"] < selected]
            + [{"from_month": selected, "lines": {**base, category: data["amount_minor"]}}]
            + [
                {**v, "lines": {**v["lines"], category: data["amount_minor"]}}
                for v in versions
                if v["from_month"] > selected
            ]
        )
        overrides = {
            m: ({k: v for k, v in values.items() if k != category} if m >= selected else values)
            for m, values in overrides.items()
        }
    else:
        overrides[selected] = {**overrides.get(selected, {}), category: data["amount_minor"]}
    return r.budgets.save(
        budget["id"], data["expected_version"], {"versions": versions, "overrides": overrides}
    )


def budget_settings(r: Repositories, data: Data) -> Data:
    budget = budget_for(r, data["currency"])
    changes = {k: v for k, v in data.items() if k not in {"currency", "expected_version"}}
    candidate = {**budget, **changes}
    require(
        candidate["savings_minor"] <= candidate["income_minor"], "Savings target exceeds income."
    )
    if "rollover" in changes:
        roll = changes["rollover"]
        month(roll["start_month"])
        for category in roll["categories"]:
            validate_category(r, category, "expense")
    return r.budgets.save(budget["id"], data["expected_version"], changes)


def budget_view(r: ReadRepositories, selected: str, currency: str) -> Data:
    month(selected)
    budget = budget_for(r, currency)
    first = min(v["from_month"] for v in budget["versions"])
    require(first <= selected <= shift_month(first, 120), "Budget range is limited to 120 months.")
    rows = visible_transactions(r, first + "-01", shift_month(selected, 1) + "-01", currency)
    used = totals([t for t in rows if t["booked_on"].startswith(selected)])["by_category"]
    lines = lines_for(budget, selected)
    carry: dict[str, int] = {}
    rollover = budget["rollover"]
    if rollover.get("enabled"):
        cursor = max(first, rollover["start_month"])
        while cursor < selected:
            past = totals([t for t in rows if t["booked_on"].startswith(cursor)])["by_category"]
            for category in rollover["categories"]:
                carry[category] = (
                    carry.get(category, 0)
                    + lines_for(budget, cursor).get(category, 0)
                    - past.get(category, 0)
                )
            cursor = shift_month(cursor, 1)
    keys = sorted(set(lines) | set(used) | set(carry))
    return {
        "budget": budget,
        "month": selected,
        "currency": currency,
        "policy_version": "dev-v1",
        "rows": [
            {
                "category_id": k,
                "planned_minor": lines.get(k, 0),
                "rollover_minor": carry.get(k, 0),
                "spent_minor": used.get(k, 0),
                "remaining_minor": lines.get(k, 0) + carry.get(k, 0) - used.get(k, 0),
            }
            for k in keys
        ],
    }


def recurring(r: Repositories, data: Data, identifier: str | None = None) -> Data:
    current = r.recurring.get(identifier) if identifier else {}
    merged = {**current, **data}
    account = r.accounts.get(merged["account_id"])
    require(not account["archived"], "Account is archived.", 409)
    minor(merged["amount_minor"], positive=True)
    require(
        not merged.get("end_on") or merged["end_on"] >= merged["next_on"],
        "End date precedes the next occurrence.",
    )
    if identifier:
        return r.recurring.save(
            identifier,
            data["expected_version"],
            {k: v for k, v in data.items() if k != "expected_version"},
        )
    return r.recurring.add({**data, "currency": account["currency"]})


def upcoming(r: ReadRepositories, start: date, end: date) -> Data:
    require(0 <= (end - start).days <= 366, "Projection range must be 0-366 days.")
    result: list[Data] = []
    series = r.recurring.list(limit=1001, filters={"stopped": False})
    require(len(series) <= 1000, "Recurring series limit exceeded.")
    for item in series:
        if r.accounts.get(item["account_id"])["archived"]:
            continue
        cursor = date.fromisoformat(item["next_on"])
        anchor_day = cursor.day
        for _ in range(1000):
            if cursor > end or (item["end_on"] and cursor > date.fromisoformat(item["end_on"])):
                break
            if cursor >= start:
                result.append(
                    {
                        "series_id": item["id"],
                        "date": cursor.isoformat(),
                        "amount_minor": item["amount_minor"],
                        "currency": item["currency"],
                        "direction": item["direction"],
                        "estimated": True,
                    }
                )
            if cursor >= end:
                break
            cursor = next_occurrence(cursor, item["frequency"], anchor_day)
        else:
            require(False, "Projection iteration bound reached; advance the schedule first.")
        require(len(result) <= 10000, "Projection item limit exceeded.")
    return {"items": sorted(result, key=lambda row: (row["date"], row["series_id"]))}
