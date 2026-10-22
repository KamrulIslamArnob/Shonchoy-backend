from uuid import UUID, uuid4

import pytest
from conftest import AUTH, TOKEN
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from fintrack_core.config import Settings
from fintrack_core.main import create_app


def add_account(client, name="Synthetic cash"):
    response = client.post("/v1/accounts", headers=AUTH, json={"name": name, "currency": "BDT"})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_auth_denies(client, headers):
    response = client.get("/v1/accounts", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["requestId"] == response.headers["x-request-id"]


def test_missing_config_is_unavailable():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/accounts").status_code == 503
    with TestClient(create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))) as client:
        assert client.get("/v1/health/ready", headers=AUTH).status_code == 503
        assert client.get("/v1/accounts", headers=AUTH).status_code == 503


def test_account_roundtrip_cursor_and_no_client_ownership(client):
    ids = {add_account(client, "First"), add_account(client, "Second")}
    page = client.get("/v1/accounts?limit=1", headers=AUTH).json()
    assert page["ok"] is True
    assert len(page["data"]["items"]) == 1
    cursor = page["data"]["nextCursor"]
    other = client.get(f"/v1/accounts?limit=1&cursor={cursor}", headers=AUTH).json()["data"]
    assert other["nextCursor"] is None
    assert {page["data"]["items"][0]["id"], other["items"][0]["id"]} == ids
    record = client.get(f"/v1/accounts/{next(iter(ids))}", headers=AUTH).json()["data"]
    assert record["currency"] == "BDT"
    assert record["createdAt"]
    assert (
        client.post(
            "/v1/accounts", headers=AUTH, json={"name": "Bad", "ownerId": "spoofed"}
        ).status_code
        == 422
    )
    assert client.get(f"/v1/accounts/{uuid4()}", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": " "},
        {"name": "x", "currency": "ZZZ"},
        {"name": "x", "currency": "bdt"},
        {"name": "x" * 121},
    ],
)
def test_account_validation(client, body):
    assert client.post("/v1/accounts", headers=AUTH, json=body).status_code == 422
    assert client.get("/v1/accounts", headers=AUTH).json()["data"]["items"] == []


@pytest.mark.parametrize("amount", [0, 1.5, "100", True, 9_000_000_000_000_001])
def test_money_boundaries(client, amount):
    account_id = add_account(client)
    response = client.post(
        "/v1/transactions",
        headers=AUTH,
        json={
            "accountId": account_id,
            "amountMinor": amount,
            "description": "Synthetic item",
            "bookedOn": "2026-10-20",
        },
    )
    assert response.status_code == 422
    assert client.get("/v1/transactions", headers=AUTH).json()["data"]["items"] == []


def test_transactions_exact_roundtrip_account_filter_and_duplicate_contract(client):
    account_id, other_id = add_account(client), add_account(client)
    body = {
        "accountId": account_id,
        "amountMinor": -12345,
        "description": "Synthetic expense",
        "bookedOn": "2026-10-20",
    }
    created = client.post("/v1/transactions", headers=AUTH, json=body)
    assert created.status_code == 201
    record = created.json()["data"]
    assert record["amountMinor"] == -12345
    assert client.get(f"/v1/transactions/{record['id']}", headers=AUTH).json()["data"] == record
    assert (
        client.get(f"/v1/transactions?accountId={other_id}", headers=AUTH).json()["data"]["items"]
        == []
    )
    assert (
        len(
            client.get(f"/v1/transactions?accountId={account_id}", headers=AUTH).json()["data"][
                "items"
            ]
        )
        == 1
    )
    duplicate = client.post("/v1/transactions", headers=AUTH, json=body)
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["id"] != record["id"]  # No idempotency claim in this scaffold.
    body["accountId"] = str(uuid4())
    assert client.post("/v1/transactions", headers=AUTH, json=body).status_code == 404
    body["accountId"], body["bookedOn"] = account_id, "2026-02-30"
    assert client.post("/v1/transactions", headers=AUTH, json=body).status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "cursor=invalid"])
def test_pagination_validation(client, query):
    assert client.get(f"/v1/accounts?{query}", headers=AUTH).status_code == 422


def test_database_write_failure_rolls_back_and_retry_succeeds(client):
    engine = client.app.state.engine

    def fail_commit(connection):
        raise OperationalError("synthetic private SQL", {}, Exception("synthetic private URL"))

    event.listen(engine, "commit", fail_commit)
    try:
        response = client.post("/v1/accounts", headers=AUTH, json={"name": "Lost write"})
    finally:
        event.remove(engine, "commit", fail_commit)
    assert response.status_code == 503
    assert "private" not in response.text
    assert client.get("/v1/accounts", headers=AUTH).json()["data"]["items"] == []
    add_account(client, "Safe retry")
    assert len(client.get("/v1/accounts", headers=AUTH).json()["data"]["items"]) == 1


def test_database_missing_schema_is_unavailable(client):
    with client.app.state.engine.begin() as connection:
        connection.execute(text("DROP TABLE dev_transactions"))
    response = client.get("/v1/health/ready", headers=AUTH)
    assert response.status_code == 503
    assert "dev_transactions" not in response.text


def test_validation_redacts_input_request_ids_are_server_owned_and_cors_is_bounded(client):
    marker = "synthetic-sensitive-body-marker"
    response = client.post(
        "/v1/accounts",
        headers={**AUTH, "X-Request-Id": marker},
        json={"name": "Test", "unexpected": marker},
    )
    assert response.status_code == 422
    assert marker not in response.text
    UUID(response.headers["x-request-id"])
    response = client.options(
        "/v1/accounts",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers
    response = client.options(
        "/v1/accounts",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_is_versioned_and_protected_routes_declare_security(client):
    schema = client.get("/v1/openapi.json").json()
    assert schema["openapi"].startswith("3.")
    for path, methods in schema["paths"].items():
        if path.startswith("/v1/"):
            for method in methods.values():
                assert method["security"] == [{"HTTPBearer": []}]


def test_non_ascii_bearer_is_denied(client):
    response = client.get("/v1/accounts", headers={"Authorization": b"Bearer \xff"})
    assert response.status_code == 401


def test_unknown_field_names_and_unexpected_failures_are_redacted(client):
    marker = "synthetic-private-input-marker"
    response = client.post("/v1/accounts", headers=AUTH, json={"name": "Synthetic", marker: marker})
    assert response.status_code == 422
    assert marker not in response.text

    @client.app.get("/test-unexpected-error")
    def unexpected():
        raise RuntimeError(marker)

    response = client.get("/test-unexpected-error")
    assert response.status_code == 500
    assert marker not in response.text
    assert response.json()["requestId"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
