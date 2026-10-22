from fintrack_core.finance.domain import Data, require
from fintrack_core.finance.ports import ReadRepositories, Repositories


def validate_category(r: ReadRepositories, identifier: str | None, kind: str) -> None:
    if identifier:
        category = r.categories.get(identifier)
        require(
            not category["archived"] and category["kind"] == kind,
            "Category is archived or does not match the transaction kind.",
        )


def category(r: Repositories, data: Data, identifier: str | None = None) -> Data:
    if data.get("group_id"):
        require(not r.groups.get(data["group_id"])["archived"], "Group is archived.")
    if identifier:
        current = r.categories.get(identifier)
        require(
            "kind" not in data or data["kind"] == current["kind"],
            "Category kind cannot be changed after creation.",
        )
        return r.categories.save(
            identifier,
            data["expected_version"],
            {k: v for k, v in data.items() if k != "expected_version"},
        )
    return r.categories.add(data)


def rule(r: Repositories, data: Data, identifier: str | None = None) -> Data:
    current = r.rules.get(identifier) if identifier else {}
    candidate = {**current, **data}
    require(
        any(
            candidate.get(k) is not None
            for k in ("merchant_contains", "min_amount_minor", "max_amount_minor", "account_id")
        ),
        "A rule must have at least one matching criterion.",
    )
    minimum, maximum = candidate.get("min_amount_minor"), candidate.get("max_amount_minor")
    require(minimum is None or maximum is None or minimum <= maximum, "Invalid rule amount range.")
    require(
        any(candidate.get(k) for k in ("set_category_id", "set_merchant", "add_tag")),
        "A rule must have an action.",
    )
    if candidate.get("account_id"):
        r.accounts.get(candidate["account_id"])
    if candidate.get("set_category_id"):
        require(
            not r.categories.get(candidate["set_category_id"])["archived"], "Category is archived."
        )
    if identifier:
        return r.rules.save(
            identifier,
            data["expected_version"],
            {k: v for k, v in data.items() if k != "expected_version"},
        )
    return r.rules.add(data)


def matches(rule: Data, transaction: Data) -> bool:
    return (
        not rule["archived"]
        and (
            not rule["merchant_contains"]
            or rule["merchant_contains"].casefold() in transaction["merchant"].casefold()
        )
        and (
            rule["min_amount_minor"] is None
            or transaction["amount_minor"] >= rule["min_amount_minor"]
        )
        and (
            rule["max_amount_minor"] is None
            or transaction["amount_minor"] <= rule["max_amount_minor"]
        )
        and (not rule["account_id"] or transaction["account_id"] == rule["account_id"])
    )


def compatible(r: ReadRepositories, rule: Data, transaction: Data) -> bool:
    if rule["set_category_id"]:
        category = r.categories.get(rule["set_category_id"])
        return not category["archived"] and category["kind"] == transaction["kind"]
    return True


def apply(r: Repositories, rule: Data, transaction: Data) -> Data:
    result = dict(transaction)
    if rule["set_category_id"]:
        validate_category(r, rule["set_category_id"], result["kind"])
        require(not result.get("splits"), "A rule cannot replace a split classification.", 409)
        result["category_id"] = rule["set_category_id"]
    if rule["set_merchant"]:
        result["merchant"] = rule["set_merchant"]
    if rule["add_tag"] and rule["add_tag"] not in result["tags"]:
        result["tags"] = [*result["tags"], rule["add_tag"]]
    result["classification_source"] = "rule"
    return result
