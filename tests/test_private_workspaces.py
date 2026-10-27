"""Real signed JWTs and two independent users against the HTTP/database boundary."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from fintrack_core.auth import authenticated_access

ORIGIN = "https://auth.example.invalid"


@pytest.fixture(params=[False, True], ids=["shared-database", "separate-auth-database"])
def private_client(client, monkeypatch, request):
    auth_engine = (
        create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        if request.param
        else client.app.state.engine
    )
    client.app.state.auth_engine = auth_engine
    client.app.dependency_overrides.pop(authenticated_access, None)
    settings = client.app.state.settings
    settings.neon_auth_url = ORIGIN + "/neondb/auth"
    settings.command_fingerprint_key = settings.dev_api_key
    private_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        "fintrack_core.auth.signing_keys",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private_key.public_key())
        ),
    )
    with auth_engine.begin() as db:
        db.execute(text("ATTACH DATABASE ':memory:' AS neon_auth"))
        db.execute(
            text(
                'CREATE TABLE neon_auth.session (id TEXT PRIMARY KEY, "userId" TEXT, '
                '"expiresAt" TIMESTAMP)'
            )
        )

    def login(subject):
        session_id = str(uuid4())
        with auth_engine.begin() as db:
            db.execute(
                text("INSERT INTO neon_auth.session VALUES (:id, :user, :expiry)"),
                {
                    "id": session_id,
                    "user": subject,
                    "expiry": datetime.now(UTC) + timedelta(hours=1),
                },
            )
        now = datetime.now(UTC)
        claims = {
            "sub": subject,
            "iss": ORIGIN,
            "aud": ORIGIN,
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "name": subject,
        }
        token = jwt.encode(claims, private_key, algorithm="EdDSA", headers={"kid": "test"})
        return {"Authorization": f"Bearer {token}", "X-Neon-Session-Id": session_id}

    yield client, login, private_key
    if request.param:
        auth_engine.dispose()


def create(client, headers, path="/accounts", body=None, key="same-command-key"):
    return client.post(
        "/v1/core" + path,
        headers={**headers, "Idempotency-Key": key},
        json=body or {"name": "Private cash"},
    )


def test_first_login_creates_one_private_workspace_and_user(private_client):
    client, login, _ = private_client
    alice, bob = login("alice"), login("bob")
    a = client.get("/v1/core/workspace-snapshot", headers=alice)
    b = client.get("/v1/core/workspace-snapshot", headers=bob)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()["data"]["profile"]["id"] != b.json()["data"]["profile"]["id"]
    assert a.json()["data"]["accounts"] == b.json()["data"]["accounts"] == []
    again = client.get("/v1/core/me", headers=login("alice"))
    assert again.json()["data"]["id"] == a.json()["data"]["profile"]["id"]
    with client.app.state.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM core_users")).scalar() == 2


def test_other_user_cannot_read_edit_or_reference_account_and_keys_are_private(private_client):
    client, login, _ = private_client
    alice, bob = login("alice"), login("bob")
    a, b = create(client, alice), create(client, bob)
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    aid, bid = a.json()["data"]["id"], b.json()["data"]["id"]
    assert aid != bid
    assert create(client, alice).json()["data"]["id"] == aid
    assert client.get(f"/v1/core/accounts/{aid}", headers=bob).status_code == 404
    patch = client.patch(
        f"/v1/core/accounts/{aid}",
        headers={**bob, "Idempotency-Key": str(uuid4())},
        json={"name": "Stolen", "expectedVersion": 1},
    )
    assert patch.status_code == 404
    attempt = create(
        client,
        bob,
        "/transactions",
        {"accountId": aid, "amountMinor": 100, "merchant": "Other user", "bookedOn": "2026-10-27"},
        key=str(uuid4()),
    )
    assert attempt.status_code == 404
    snapshot = client.get("/v1/core/workspace-snapshot", headers=bob).json()["data"]
    assert [row["id"] for row in snapshot["accounts"]] == [bid]
    assert snapshot["transactions"] == []


def test_revocation_and_session_ownership_are_checked_on_every_request(private_client):
    client, login, _ = private_client
    alice, bob = login("alice"), login("bob")
    assert create(client, alice).status_code == 201
    forged = {**alice, "X-Neon-Session-Id": bob["X-Neon-Session-Id"]}
    assert client.get("/v1/core/me", headers=forged).status_code == 401
    with client.app.state.auth_engine.begin() as db:
        db.execute(
            text("DELETE FROM neon_auth.session WHERE id=:id"), {"id": alice["X-Neon-Session-Id"]}
        )
    assert client.get("/v1/core/me", headers=alice).status_code == 401
    assert create(client, alice).status_code == 401
    assert client.get("/v1/core/me", headers=bob).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"iss": "https://evil.invalid"},
        {"aud": "other-app"},
        {"sub": ""},
        {"banned": True},
    ],
)
def test_invalid_claims_fail_closed(private_client, change):
    client, login, key = private_client
    headers = login("alice")
    now = datetime.now(UTC)
    claims = {
        "sub": "alice",
        "iss": ORIGIN,
        "aud": ORIGIN,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        **change,
    }
    token = jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "test"})
    headers["Authorization"] = f"Bearer {token}"
    assert client.get("/v1/core/me", headers=headers).status_code == 401


@pytest.mark.parametrize(
    ("issued_offset", "expiry_offset", "expected"),
    [(20, 900, 200), (90, 900, 401), (-900, -90, 401)],
    ids=["small-issuer-clock-skew", "future-token-denied", "expired-token-denied"],
)
def test_token_clock_skew_is_bounded(private_client, issued_offset, expiry_offset, expected):
    client, login, key = private_client
    headers = login("alice")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "alice",
            "iss": ORIGIN,
            "aud": ORIGIN,
            "iat": now + timedelta(seconds=issued_offset),
            "exp": now + timedelta(seconds=expiry_offset),
        },
        key,
        algorithm="EdDSA",
        headers={"kid": "test"},
    )
    headers["Authorization"] = f"Bearer {token}"
    assert client.get("/v1/core/me", headers=headers).status_code == expected


def test_no_shared_key_or_unsigned_token_can_enter_finance(private_client):
    client, login, _ = private_client
    headers = login("alice")
    for token in [
        "wrong",
        client.app.state.settings.dev_api_key.get_secret_value(),
        jwt.encode({"sub": "alice"}, "", algorithm="none"),
    ]:
        assert (
            client.get(
                "/v1/core/me", headers={**headers, "Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
    assert client.get("/v1/core/me").status_code == 401
    assert (
        client.get("/v1/core/me", headers={"Authorization": headers["Authorization"]}).status_code
        == 401
    )


def test_auth_database_failure_denies_access_without_provisioning(private_client):
    client, login, _ = private_client
    headers = login("alice")
    with client.app.state.auth_engine.begin() as db:
        db.execute(text("DROP TABLE neon_auth.session"))
    response = client.get("/v1/core/me", headers=headers)
    assert response.status_code == 503
    assert "neon_auth" not in response.text
    with client.app.state.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM core_users")).scalar() == 0
