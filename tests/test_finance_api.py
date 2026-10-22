from datetime import date
from uuid import uuid4

from conftest import AUTH
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m

ROOT = "/v1/core"


def command(client, path, body, *, key=None, method="post", expected=200):
    response = getattr(client, method)(
        ROOT + path, json=body, headers={**AUTH, "Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code == expected, response.text
    return response.json()["data"]


def account(client, **patch):
    return command(
        client,
        "/accounts",
        {"name": "Synthetic cash", "balanceMinor": 50000, **patch},
        expected=201,
    )


def category(client, name="Synthetic groceries", **patch):
    return command(client, "/categories", {"name": name, **patch}, expected=201)


def transaction(client, account_id, **patch):
    return command(
        client,
        "/transactions",
        {
            "accountId": account_id,
            "amountMinor": 10000,
            "merchant": "Synthetic merchant",
            "bookedOn": "2026-10-20",
            **patch,
        },
        expected=201,
    )


def get(client, path):
    response = client.get(ROOT + path, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def count(client, model):
    with Session(client.app.state.engine) as db:
        return db.scalar(select(func.count()).select_from(model))


def test_commands_require_auth_keys_and_reject_authority_fields(client):
    assert client.get(ROOT + "/bootstrap").status_code == 401
    assert (
        client.post(ROOT + "/accounts", headers=AUTH, json={"name": "Synthetic"}).status_code == 428
    )
    response = client.post(
        ROOT + "/accounts",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"name": "Synthetic", "ownerId": "forged"},
    )
    assert response.status_code == 422
    assert count(client, m.Account) == 0
    assert len(get(client, "/bootstrap")["currencies"]) == 10


def test_idempotency_replay_mismatch_and_stale_updates(client):
    key = str(uuid4())
    first = command(client, "/accounts", {"name": "Synthetic"}, key=key, expected=201)
    repeat = command(client, "/accounts", {"name": "Synthetic"}, key=key, expected=201)
    assert repeat == first
    assert count(client, m.Account) == count(client, m.Audit) == count(client, m.Outbox) == 1
    response = client.post(
        ROOT + "/accounts", headers={**AUTH, "Idempotency-Key": key}, json={"name": "Different"}
    )
    assert response.status_code == 409
    updated = command(
        client, f"/accounts/{first['id']}", {"name": "New", "expectedVersion": 1}, method="patch"
    )
    assert updated["version"] == 2
    response = client.patch(
        ROOT + f"/accounts/{first['id']}",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"name": "Stale", "expectedVersion": 1},
    )
    assert response.status_code == 409
    assert get(client, f"/accounts/{first['id']}")["name"] == "New"
    assert command(client, "/accounts", {"name": "Synthetic"}, key=key, expected=201) == first


def test_connected_money_reports_splits_refunds_transfer_and_balance_observations(client):
    source, target = account(client), account(client, name="Second")
    cat1, cat2 = category(client), category(client, "Other")
    tx = transaction(
        client,
        source["id"],
        splits=[
            {"categoryId": cat1["id"], "amountMinor": 6000},
            {"categoryId": cat2["id"], "amountMinor": 4000},
        ],
    )
    transaction(client, source["id"], amountMinor=500, direction="in", categoryId=cat1["id"])
    transaction(client, source["id"], amountMinor=100000, direction="in", kind="income")
    transaction(client, source["id"], amountMinor=999, pending=True)
    transfer = command(
        client,
        "/transfers",
        {
            "fromAccountId": source["id"],
            "toAccountId": target["id"],
            "fromExpectedVersion": 1,
            "toExpectedVersion": 1,
            "amountMinor": 2000,
            "bookedOn": "2026-10-20",
        },
        expected=201,
    )
    assert [i["direction"] for i in transfer["items"]] == ["out", "in"]
    summary = get(client, "/dashboard/summary?selected=2026-10")
    assert summary["cashflow"] == {
        "incomeMinor": 100000,
        "expenseMinor": 9500,
        "netMinor": 90500,
        "byCategory": {cat1["id"]: 5500, cat2["id"]: 4000},
    }
    assert summary["assetsMinor"] == 100000  # Observations are independent of transaction edits.
    assert get(client, "/reports/spending?selected=2026-10") == summary
    hidden = command(
        client, f"/transactions/{tx['id']}/visibility", {"expectedVersion": 1, "hidden": True}
    )
    assert hidden["version"] == 2
    assert get(client, "/dashboard/summary?selected=2026-10")["cashflow"]["expenseMinor"] == -500
    observed = command(
        client,
        f"/accounts/{source['id']}/balance-observations",
        {"expectedVersion": 1, "amountMinor": 60000, "effectiveOn": date.today().isoformat()},
        expected=201,
    )
    assert observed["account"]["version"] == 2
    assert len(get(client, f"/accounts/{source['id']}/balance-observations")["items"]) == 2


def test_validation_split_conservation_archive_and_recoverable_delete(client):
    acct, cat = account(client), category(client)
    response = client.post(
        ROOT + "/transactions",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={
            "accountId": acct["id"],
            "amountMinor": 1000,
            "merchant": "Synthetic",
            "bookedOn": "2026-10-20",
            "splits": [{"categoryId": cat["id"], "amountMinor": 999}],
        },
    )
    assert response.status_code == 422
    assert count(client, m.Transaction) == 0
    tx = transaction(client, acct["id"])
    deleted = command(client, f"/transactions/{tx['id']}/delete", {"expectedVersion": 1})
    assert deleted["deleted"]
    assert get(client, "/transactions")["items"] == []
    restored = command(client, f"/transactions/{tx['id']}/restore", {"expectedVersion": 2})
    assert restored["version"] == 3 and not restored["deleted"]
    command(client, f"/accounts/{acct['id']}/archive", {"expectedVersion": 1})
    assert get(client, f"/transactions/{tx['id']}")["id"] == tx["id"]
    response = client.post(
        ROOT + "/transactions",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={
            "accountId": acct["id"],
            "amountMinor": 1000,
            "merchant": "Synthetic",
            "bookedOn": "2026-10-20",
        },
    )
    assert response.status_code == 409
    command(client, f"/accounts/{acct['id']}/restore", {"expectedVersion": 2})


def test_transfer_failure_rolls_back_first_leg_and_can_retry(client):
    source, target = account(client), account(client)
    command(client, f"/accounts/{target['id']}/archive", {"expectedVersion": 1})
    before = count(client, m.Audit)
    key = str(uuid4())
    payload = {
        "fromAccountId": source["id"],
        "toAccountId": target["id"],
        "fromExpectedVersion": 1,
        "toExpectedVersion": 2,
        "amountMinor": 100,
        "bookedOn": "2026-10-20",
    }
    response = client.post(
        ROOT + "/transfers", headers={**AUTH, "Idempotency-Key": key}, json=payload
    )
    assert response.status_code == 409
    assert count(client, m.Transaction) == 0 and count(client, m.Audit) == before
    command(client, f"/accounts/{target['id']}/restore", {"expectedVersion": 2})
    payload["toExpectedVersion"] = 3
    pair = command(client, "/transfers", payload, key=key, expected=201)
    command(
        client,
        f"/transactions/{pair['items'][0]['id']}/delete",
        {"expectedVersion": 1, "pairedExpectedVersion": 1},
    )
    assert all(t["deleted"] for t in get(client, "/transactions?includeDeleted=true")["items"])


def test_outbox_failure_rolls_back_entity_idempotency_and_audit(client):
    engine = client.app.state.engine

    def reject_outbox(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO core_outbox"):
            raise OperationalError("private SQL", {}, Exception("private payload"))

    event.listen(engine, "before_cursor_execute", reject_outbox)
    key = str(uuid4())
    try:
        response = client.post(
            ROOT + "/accounts", headers={**AUTH, "Idempotency-Key": key}, json={"name": "Synthetic"}
        )
    finally:
        event.remove(engine, "before_cursor_execute", reject_outbox)
    assert response.status_code == 503 and "private" not in response.text
    for model in [m.Account, m.Observation, m.Idempotency, m.Audit, m.Outbox]:
        assert count(client, model) == 0
    command(client, "/accounts", {"name": "Synthetic"}, key=key, expected=201)


def test_budget_month_future_overrides_and_negative_rollover(client):
    acct, cat = account(client), category(client)
    budget = command(
        client,
        "/budgets/2026-10",
        {"incomeMinor": 100000, "savingsMinor": 20000, "lines": {cat["id"]: 10000}},
        method="put",
        expected=201,
    )
    transaction(client, acct["id"], amountMinor=12000, categoryId=cat["id"])
    command(
        client,
        "/budgets",
        {
            "expectedVersion": budget["version"],
            "rollover": {"enabled": True, "categories": [cat["id"]], "startMonth": "2026-10"},
        },
        method="patch",
    )
    command(
        client,
        "/budgets/2026-11/lines",
        {"expectedVersion": 2, "categoryId": cat["id"], "amountMinor": 9000},
    )
    command(
        client,
        "/budgets/2026-12/lines",
        {"expectedVersion": 3, "categoryId": cat["id"], "amountMinor": 11000, "applyFuture": True},
    )
    november = get(client, "/budgets/2026-11")["rows"][0]
    december = get(client, "/budgets/2026-12")["rows"][0]
    assert november["rolloverMinor"] == -2000 and november["remainingMinor"] == 7000
    assert december["rolloverMinor"] == 7000 and december["remainingMinor"] == 18000
    stale = client.post(
        ROOT + "/budgets/2026-11/lines",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"expectedVersion": 1, "categoryId": cat["id"], "amountMinor": 1},
    )
    assert stale.status_code == 409


def test_recurring_month_end_projection_is_estimated_and_never_posts(client):
    acct = account(client)
    recurring = command(
        client,
        "/recurring",
        {
            "accountId": acct["id"],
            "name": "Synthetic bill",
            "amountMinor": 100,
            "frequency": "monthly",
            "nextOn": "2027-01-31",
        },
        expected=201,
    )
    items = get(client, "/recurring/upcoming?start=2027-01-01&end=2027-03-31")["items"]
    assert [i["date"] for i in items] == ["2027-01-31", "2027-02-28", "2027-03-31"]
    assert all(i["estimated"] for i in items) and count(client, m.Transaction) == 0
    command(
        client,
        f"/recurring/{recurring['id']}",
        {"expectedVersion": 1, "stopped": True},
        method="patch",
    )
    assert get(client, "/recurring/upcoming?start=2027-01-01&end=2027-03-31")["items"] == []


def test_rule_preview_manual_override_and_idempotent_application(client):
    acct, cat = account(client), category(client)
    tx = transaction(client, acct["id"])
    rule = command(
        client,
        "/rules",
        {"merchantContains": "Synthetic", "setCategoryId": cat["id"]},
        expected=201,
    )
    preview = get(client, f"/rules/{rule['id']}/preview")
    assert preview["items"][0]["id"] == tx["id"]
    command(
        client,
        f"/transactions/{tx['id']}",
        {"expectedVersion": 1, "categoryId": cat["id"]},
        method="patch",
    )
    result = command(
        client,
        f"/rules/{rule['id']}/applications",
        {"expectedVersion": 1, "items": preview["items"]},
    )
    assert result["items"] == [] and result["skippedIds"] == [tx["id"]]
    future = transaction(client, acct["id"])
    assert future["categoryId"] == cat["id"] and future["classificationSource"] == "rule"


def test_profile_pagination_currency_isolation_and_invalid_null_patch(client):
    assert get(client, "/me")["version"] == 1
    profile = command(
        client,
        "/me/profile",
        {"expectedVersion": 1, "name": "Synthetic user", "currency": "JPY", "onboarded": True},
        method="patch",
    )
    assert profile["version"] == 2 and profile["currency"] == "JPY"
    a = account(client, currency="JPY", balanceMinor=123)
    account(client, currency="BDT", balanceMinor=456)
    first = get(client, "/accounts?limit=1")
    assert len(first["items"]) == 1
    assert len(get(client, f"/accounts?limit=1&cursor={first['nextCursor']}")["items"]) == 1
    assert get(client, "/dashboard/summary?selected=2026-10&currency=JPY")["assetsMinor"] == 123
    invalid = client.patch(
        ROOT + f"/accounts/{a['id']}",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"expectedVersion": 1, "name": None},
    )
    assert invalid.status_code == 422


def test_hidden_accounts_have_same_spending_policy_in_budget_and_reports(client):
    acct, cat = account(client), category(client)
    transaction(client, acct["id"], categoryId=cat["id"])
    command(
        client,
        "/budgets/2026-10",
        {"incomeMinor": 20000, "savingsMinor": 0, "lines": {cat["id"]: 15000}},
        method="put",
        expected=201,
    )
    command(
        client, f"/accounts/{acct['id']}", {"expectedVersion": 1, "hidden": True}, method="patch"
    )
    assert get(client, "/budgets/2026-10")["rows"][0]["spentMinor"] == 0
    summary = get(client, "/reports/spending?selected=2026-10")
    assert summary["cashflow"]["expenseMinor"] == 0
    assert summary["balanceHistoryAvailable"] is False


def test_manual_classification_is_not_overwritten_on_create_and_batch_review_is_atomic(client):
    acct, first, second = account(client), category(client), category(client, "Second")
    command(
        client,
        "/rules",
        {"merchantContains": "Synthetic", "setCategoryId": second["id"]},
        expected=201,
    )
    tx = transaction(client, acct["id"], categoryId=first["id"])
    assert tx["categoryId"] == first["id"] and tx["classificationSource"] == "manual"
    other = transaction(client, acct["id"])
    response = client.post(
        ROOT + "/transaction-reviews",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={
            "items": [
                {"id": tx["id"], "expectedVersion": 1},
                {"id": other["id"], "expectedVersion": 99},
            ]
        },
    )
    assert response.status_code == 409
    assert get(client, f"/transactions/{tx['id']}")["reviewed"] is False


def test_preferences_deny_security_claims_and_capacity_failure_is_bounded(client):
    prefs = command(
        client,
        "/me/preferences",
        {"expectedVersion": 1, "theme": "dark", "blurAmountsOnOpen": True},
        method="patch",
    )
    assert prefs["preferences"] == {"theme": "dark", "blurAmountsOnOpen": True}
    response = client.patch(
        ROOT + "/me/preferences",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"expectedVersion": 2, "mfa": True},
    )
    assert response.status_code == 422
    capacity = client.app.state.core_capacity
    for _ in range(8):
        assert capacity.acquire(blocking=False)
    try:
        assert client.get(ROOT + "/accounts", headers=AUTH).status_code == 503
    finally:
        for _ in range(8):
            capacity.release()
    assert get(client, "/accounts")["items"] == []


def test_aggregate_safe_integer_range_is_enforced(client):
    account(client, balanceMinor=9_000_000_000_000_000)
    account(client, balanceMinor=9_000_000_000_000_000)
    response = client.get(ROOT + "/dashboard/summary?selected=2026-10", headers=AUTH)
    assert response.status_code == 422


def test_incompatible_or_archived_automatic_rules_do_not_block_valid_transactions(client):
    acct, cat = account(client), category(client)
    command(
        client,
        "/rules",
        {"merchantContains": "Synthetic", "setCategoryId": cat["id"]},
        expected=201,
    )
    income = transaction(client, acct["id"], kind="income", direction="in")
    assert income["categoryId"] is None
    command(
        client, f"/categories/{cat['id']}", {"expectedVersion": 1, "archived": True}, method="patch"
    )
    expense = transaction(client, acct["id"])
    assert expense["categoryId"] is None
    assert get(client, "/health/ready")["status"] == "ready"


def test_atomic_amount_and_split_correction_and_archived_category_history(client):
    acct, cat = account(client), category(client)
    tx = transaction(client, acct["id"], splits=[{"categoryId": cat["id"], "amountMinor": 10000}])
    edited = command(
        client,
        f"/transactions/{tx['id']}",
        {
            "expectedVersion": 1,
            "amountMinor": 20000,
            "splits": [{"categoryId": cat["id"], "amountMinor": 20000}],
        },
        method="patch",
    )
    assert edited["amountMinor"] == edited["splits"][0]["amountMinor"] == 20000
    plain = transaction(client, acct["id"], categoryId=cat["id"])
    command(
        client, f"/categories/{cat['id']}", {"expectedVersion": 1, "archived": True}, method="patch"
    )
    note = command(
        client,
        f"/transactions/{plain['id']}",
        {"expectedVersion": 1, "notes": "Synthetic note"},
        method="patch",
    )
    assert note["categoryId"] == cat["id"] and note["notes"] == "Synthetic note"


def test_debit_metadata_must_attach_to_deposit_and_rule_null_is_validation_error(client):
    response = client.post(
        ROOT + "/accounts",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"name": "Synthetic cash", "debitCardLast4": "1234"},
    )
    assert response.status_code == 422
    deposit = account(client, kind="checking", debitCardLast4="1234")
    assert deposit["debitCardLast4"] == "1234"
    rule = command(
        client, "/rules", {"merchantContains": "Synthetic", "addTag": "synthetic"}, expected=201
    )
    response = client.patch(
        ROOT + f"/rules/{rule['id']}",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"expectedVersion": 1, "archived": None},
    )
    assert response.status_code == 422


def test_openapi_marks_command_header_required_and_core_readiness_reports_missing_schema(client):
    schema = client.get("/v1/openapi.json").json()
    operation = schema["paths"][ROOT + "/accounts"]["post"]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in operation["parameters"])
    from sqlalchemy import text

    with client.app.state.engine.begin() as db:
        db.execute(text("DROP TABLE core_outbox"))
    assert client.get(ROOT + "/health/ready", headers=AUTH).status_code == 503
    # Atomic commands also require their journal tables.
    response = client.post(
        ROOT + "/accounts",
        headers={**AUTH, "Idempotency-Key": str(uuid4())},
        json={"name": "Synthetic"},
    )
    assert response.status_code == 503
    assert count(client, m.Account) == 0
