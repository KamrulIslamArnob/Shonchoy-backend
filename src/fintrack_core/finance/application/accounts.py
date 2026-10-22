from datetime import date

from fintrack_core.finance.domain import CURRENCIES, KINDS, Data, minor, require
from fintrack_core.finance.ports import Repositories


def create(r: Repositories, data: Data) -> Data:
    require(data["currency"] in CURRENCIES and data["kind"] in KINDS, "Unsupported account.")
    minor(data["balance_minor"])
    require(
        not data.get("debit_card_last4") or data["kind"] in {"checking", "savings"},
        "Debit-card metadata must attach to a checking or savings account.",
    )
    require(
        data["is_asset"] == (data["kind"] not in {"credit", "loan", "mortgage"}),
        "Account asset/debt classification does not match its kind.",
    )
    account = r.accounts.add(data)
    r.observations.add(
        {
            "account_id": account["id"],
            "amount_minor": account["balance_minor"],
            "effective_on": date.today().isoformat(),
        }
    )
    return account


def batch(r: Repositories, data: Data) -> Data:
    return {"items": [create(r, item) for item in data["items"]]}


def edit(r: Repositories, identifier: str, data: Data) -> Data:
    current = r.accounts.get(identifier)
    changes = {k: v for k, v in data.items() if k != "expected_version"}
    require(bool(changes), "No account changes supplied.")
    require(
        not changes.get("debit_card_last4") or current["kind"] in {"checking", "savings"},
        "Debit-card metadata must attach to a checking or savings account.",
    )
    return r.accounts.save(identifier, data["expected_version"], changes)


def lifecycle(r: Repositories, identifier: str, data: Data, archived: bool) -> Data:
    return r.accounts.save(identifier, data["expected_version"], {"archived": archived})


def observe(r: Repositories, identifier: str, data: Data) -> Data:
    account = r.accounts.get(identifier)
    require(not account["archived"], "Archived account cannot be reconciled.", 409)
    minor(data["amount_minor"])
    # Historical observations are recorded, but cannot replace a newer effective observation.
    previous = r.observations.list(limit=10001, filters={"account_id": identifier})
    require(len(previous) <= 10000, "Observation history limit reached.")
    require(
        not previous or data["effective_on"] >= max(p["effective_on"] for p in previous),
        "A balance observation cannot supersede a later observation.",
        409,
    )
    observation = r.observations.add(
        {
            "account_id": identifier,
            "amount_minor": data["amount_minor"],
            "effective_on": data["effective_on"],
        }
    )
    updated = r.accounts.save(
        identifier, data["expected_version"], {"balance_minor": data["amount_minor"]}
    )
    return {"account": updated, "observation": observation}
