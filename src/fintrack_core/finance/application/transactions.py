from uuid import uuid4

from fintrack_core.finance.application import catalog
from fintrack_core.finance.domain import Data, require, validate_transaction
from fintrack_core.finance.ports import ReadRepositories, Repositories


def create(r: Repositories, data: Data, *, paired: bool = False) -> Data:
    account = r.accounts.get(data["account_id"])
    require(not account["archived"], "Cannot add a transaction to an archived account.", 409)
    candidate = {**data, "currency": account["currency"]}
    require(
        candidate["kind"] != "transfer" or paired, "Create transfers through the paired command."
    )
    validate_transaction(candidate)
    catalog.validate_category(r, candidate.get("category_id"), candidate["kind"])
    for part in candidate.get("splits", []):
        catalog.validate_category(r, part["category_id"], candidate["kind"])
    candidate["classification_source"] = (
        "manual" if candidate.get("category_id") or candidate.get("splits") else "unclassified"
    )
    rules = r.rules.list(limit=1001)
    require(len(rules) <= 1000, "Rule limit exceeded.")
    for rule in sorted(rules, key=lambda item: (item["created_at"], item["id"])):
        if (
            candidate["kind"] != "transfer"
            and candidate["classification_source"] != "manual"
            and catalog.matches(rule, candidate)
            and catalog.compatible(r, rule, candidate)
        ):
            candidate = catalog.apply(r, rule, candidate)
    return r.transactions.add(candidate)


def edit(r: Repositories, identifier: str, data: Data) -> Data:
    current = r.transactions.get(identifier)
    require(not current["deleted"], "Restore a deleted transaction before editing it.", 409)
    changes = {k: v for k, v in data.items() if k != "expected_version"}
    require(bool(changes), "No transaction changes supplied.")
    require(current["kind"] != "transfer", "Paired transfers cannot be edited independently.", 409)
    require(not r.accounts.get(current["account_id"])["archived"], "Account is archived.", 409)
    if "category_id" in changes:
        require(
            not current["splits"] or changes.get("splits") == [],
            "Clear splits explicitly before changing the parent category.",
            409,
        )
    merged = {**current, **changes}
    validate_transaction(merged)
    if "category_id" in changes or "kind" in changes:
        catalog.validate_category(r, merged.get("category_id"), merged["kind"])
    if "splits" in changes or "kind" in changes:
        for part in merged["splits"]:
            catalog.validate_category(r, part["category_id"], merged["kind"])
    if any(k in changes for k in ("category_id", "kind", "merchant", "splits")):
        changes["classification_source"] = "manual"
    return r.transactions.save(identifier, data["expected_version"], changes)


def flags(r: Repositories, identifier: str, data: Data, changes: Data) -> Data:
    current = r.transactions.get(identifier)
    if "deleted" in changes and current["transfer_pair_id"]:
        pair = r.transactions.list(
            limit=3, filters={"transfer_pair_id": current["transfer_pair_id"]}
        )
        require(len(pair) == 2, "Transfer pair is incomplete.", 409)
        other = next(p for p in pair if p["id"] != identifier)
        require(
            data.get("paired_expected_version") is not None,
            "Paired transfer deletion/restoration requires both versions.",
        )
        r.transactions.save(other["id"], data["paired_expected_version"], changes)
    return r.transactions.save(identifier, data["expected_version"], changes)


def splits(r: Repositories, identifier: str, data: Data) -> Data:
    current = r.transactions.get(identifier)
    require(not current["deleted"], "Restore the transaction before editing splits.", 409)
    validate_transaction({**current, "splits": data["splits"]})
    for part in data["splits"]:
        catalog.validate_category(r, part["category_id"], current["kind"])
    return r.transactions.save(
        identifier,
        data["expected_version"],
        {"splits": data["splits"], "classification_source": "manual"},
    )


def transfer(r: Repositories, data: Data) -> Data:
    source, target = r.accounts.get(data["from_account_id"]), r.accounts.get(data["to_account_id"])
    require(source["id"] != target["id"], "Transfer accounts must differ.")
    require(source["currency"] == target["currency"], "Cross-currency transfers are not enabled.")
    require(
        source["version"] == data["from_expected_version"]
        and target["version"] == data["to_expected_version"],
        "Account changed. Refresh before transfer.",
        409,
    )
    require(
        source["is_asset"] and target["is_asset"],
        "Development transfers support asset accounts only; debt payment policy is deferred.",
    )
    pair = str(uuid4())
    common = {
        "amount_minor": data["amount_minor"],
        "booked_on": data["booked_on"],
        "merchant": data["description"],
        "kind": "transfer",
        "category_id": None,
        "notes": "",
        "tags": [],
        "splits": [],
        "reviewed": True,
        "pending": False,
        "hidden": False,
        "deleted": False,
        "transfer_pair_id": pair,
    }
    return {
        "transfer_pair_id": pair,
        "items": [
            create(r, {**common, "account_id": source["id"], "direction": "out"}, paired=True),
            create(r, {**common, "account_id": target["id"], "direction": "in"}, paired=True),
        ],
    }


def review_batch(r: Repositories, data: Data) -> Data:
    require(
        len({item["id"] for item in data["items"]}) == len(data["items"]), "Duplicate review item."
    )
    return {
        "items": [
            r.transactions.save(
                item["id"], item["expected_version"], {"reviewed": data["reviewed"]}
            )
            for item in data["items"]
        ]
    }


def preview_rule(r: ReadRepositories, identifier: str) -> Data:
    rule = r.rules.get(identifier)
    rows = r.transactions.list(limit=10001, filters={"deleted": False})
    require(len(rows) <= 10000, "Rule preview requires a smaller dataset.")
    return {
        "rule_id": identifier,
        "rule_version": rule["version"],
        "items": [
            {"id": t["id"], "expected_version": t["version"]}
            for t in rows
            if t["kind"] != "transfer"
            and t["classification_source"] != "manual"
            and catalog.matches(rule, t)
            and catalog.compatible(r, rule, t)
        ],
    }


def apply_rule(r: Repositories, identifier: str, data: Data) -> Data:
    rule = r.rules.get(identifier)
    require(rule["version"] == data["expected_version"], "Rule changed. Preview again.", 409)
    require(len({i["id"] for i in data["items"]}) == len(data["items"]), "Duplicate rule target.")
    applied, skipped = [], []
    for item in data["items"]:
        current = r.transactions.get(item["id"])
        if (
            current["version"] != item["expected_version"]
            or current["deleted"]
            or current["kind"] == "transfer"
            or current["classification_source"] == "manual"
            or not catalog.matches(rule, current)
            or not catalog.compatible(r, rule, current)
        ):
            skipped.append(current["id"])
            continue
        result = catalog.apply(r, rule, current)
        changes = {
            k: result[k] for k in ("merchant", "category_id", "tags", "classification_source")
        }
        applied.append(r.transactions.save(current["id"], current["version"], changes))
    return {"items": applied, "skipped_ids": skipped}
