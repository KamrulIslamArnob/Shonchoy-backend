"""Real signed JWTs and two independent users against the HTTP/database boundary."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, event, text
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
        db.execute(
            text(
                'CREATE TABLE neon_auth."user" (id TEXT PRIMARY KEY, name TEXT, email TEXT, '
                '"emailVerified" BOOLEAN)'
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


def test_advisor_gateway_requires_auth_and_forwards_only_capability(private_client, monkeypatch):
    from pydantic import SecretStr

    from fintrack_advisor.privacy import Capability

    client, login, _ = private_client
    settings = client.app.state.settings
    settings.advisor_service_url = "http://localhost:8001"
    settings.advisor_service_key = SecretStr("synthetic-service-key")
    calls = []

    async def fake_fetch(url, key, capability):
        calls.append((url, key.get_secret_value(), capability))
        return "Generic explanation"

    monkeypatch.setattr("fintrack_core.finance.transport.advisor.fetch_explanation", fake_fetch)
    path = "/v1/core/advisor/explanation"
    assert client.post(path, json={"capability": "spending", "consent": True}).status_code == 401
    headers = login("alice-private-name")
    assert (
        client.post(
            path, headers=headers, json={"capability": "spending", "consent": True, "amount": 5000}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, headers=headers, json={"capability": "spending", "consent": False}
        ).status_code
        == 422
    )
    assert not calls
    response = client.post(path, headers=headers, json={"capability": "spending", "consent": True})
    assert response.status_code == 200
    assert response.json()["data"]["answer"] == "Generic explanation"
    assert calls == [("http://localhost:8001", "synthetic-service-key", Capability.SPENDING)]


@pytest.mark.parametrize("provider_kind", ["openai", "anthropic"])
def test_advisor_end_to_end_never_sends_user_data_to_provider(
    private_client, monkeypatch, provider_kind
):
    import httpx
    from pydantic import SecretStr

    from fintrack_advisor.config import ProviderSettings
    from fintrack_advisor.config import Settings as AdvisorSettings
    from fintrack_advisor.main import create_app as create_advisor
    from fintrack_advisor.providers import HostedProvider

    client, login, _ = private_client
    service_key = "synthetic-service-key-" + "x" * 32
    service = create_advisor(
        AdvisorSettings(_env_file=None, dev_api_key=SecretStr(service_key)),
        ProviderSettings(_env_file=None, provider="disabled"),
    )
    sent = []

    def provider_reply(request):
        sent.append(request)
        if provider_kind == "openai":
            body = {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "Generic"}]}
                ]
            }
        else:
            body = {"content": [{"type": "text", "text": "Generic"}]}
        return httpx.Response(200, json=body)

    service.state.provider = HostedProvider(
        provider_kind,
        "test-model",
        SecretStr("synthetic-provider-key"),
        transport=httpx.MockTransport(provider_reply),
    )
    real_client = httpx.AsyncClient

    def test_client(**kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.ASGITransport(app=service)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", test_client)
    client.app.state.settings.advisor_service_url = "http://localhost:8001"
    client.app.state.settings.advisor_service_key = SecretStr(service_key)
    headers = login("Alice-private-identity")
    response = client.post(
        "/v1/core/advisor/explanation",
        headers=headers,
        json={"capability": "spending", "consent": True},
    )
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    payload = sent[0].content.decode()
    for secret in ("Alice-private-identity", "500000", headers["X-Neon-Session-Id"], service_key):
        assert secret not in payload
        assert secret not in str(sent[0].headers)


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


def test_directory_search_requires_auth_and_returns_only_verified_other_users(private_client):
    client, login, _ = private_client
    alice = login("alice")
    with client.app.state.auth_engine.begin() as db:
        db.execute(
            text(
                'INSERT INTO neon_auth."user" (id, name, email, "emailVerified") '
                "VALUES (:id, :name, :email, :verified)"
            ),
            [
                {"id": "alice", "name": "Alice", "email": "alice@example.test", "verified": True},
                {"id": "bob", "name": "Bob Smith", "email": "bob@example.test", "verified": True},
                {
                    "id": "eve",
                    "name": "Bob Unverified",
                    "email": "eve@example.test",
                    "verified": False,
                },
            ],
        )
    assert client.get("/v1/core/user-directory", params={"q": "bob"}).status_code == 401
    response = client.get("/v1/core/user-directory", params={"q": "bOb"}, headers=alice)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"] == [
        {"id": "bob", "name": "Bob Smith", "email": "bob@example.test"}
    ]
    assert (
        client.get("/v1/core/user-directory", params={"q": "alice"}, headers=alice).json()["data"][
            "items"
        ]
        == []
    )
    assert client.get(
        "/v1/core/user-directory", params={"q": "example.test"}, headers=alice
    ).json()["data"]["items"] == [{"id": "bob", "name": "Bob Smith", "email": "bob@example.test"}]
    assert (
        client.get("/v1/core/user-directory", params={"q": "%%"}, headers=alice).json()["data"][
            "items"
        ]
        == []
    )


def test_directory_uses_two_reads_no_workspace_writes_and_checks_revocation(private_client):
    client, login, _ = private_client
    alice = login("alice")
    other = login("other")
    forged = {**alice, "X-Neon-Session-Id": other["X-Neon-Session-Id"]}
    assert (
        client.get("/v1/core/user-directory", params={"q": "bob"}, headers=forged).status_code
        == 401
    )
    auth_engine = client.app.state.auth_engine
    with auth_engine.begin() as db:
        db.execute(
            text('INSERT INTO neon_auth."user" VALUES (:id, :name, :email, :verified)'),
            [
                {"id": "bob", "name": "Bob Smith", "email": "bob@example.test", "verified": True},
                {"id": "rob", "name": "Rob Bobson", "email": "rob@example.test", "verified": True},
                {
                    "id": "bangla",
                    "name": "বাংলা রহমান",
                    "email": "bangla@example.test",
                    "verified": True,
                },
            ],
        )
    statements = []

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engines = {auth_engine, client.app.state.engine}
    for engine in engines:
        event.listen(engine, "before_cursor_execute", record_sql)
    try:
        result = client.get("/v1/core/user-directory", params={"q": "bo"}, headers=alice)
        assert result.status_code == 200, result.text
        assert [row["id"] for row in result.json()["data"]["items"]] == ["bob"]
        assert len(statements) == 2
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        assert "neon_auth.session" in statements[0]
        assert "neon_auth.user" in statements[1].replace('"', "")
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", record_sql)
    result = client.get("/v1/core/user-directory", params={"q": "bob"}, headers=alice)
    assert [row["id"] for row in result.json()["data"]["items"]] == ["bob", "rob"]
    result = client.get("/v1/core/user-directory", params={"q": "BOB@example.test"}, headers=alice)
    assert [row["id"] for row in result.json()["data"]["items"]] == ["bob"]
    result = client.get("/v1/core/user-directory", params={"q": "বাংলা"}, headers=alice)
    assert [row["id"] for row in result.json()["data"]["items"]] == ["bangla"]
    with auth_engine.begin() as db:
        db.execute(
            text("DELETE FROM neon_auth.session WHERE id=:id"), {"id": alice["X-Neon-Session-Id"]}
        )
    assert (
        client.get("/v1/core/user-directory", params={"q": "bob"}, headers=alice).status_code == 401
    )


def test_directory_only_includes_explicit_test_fixtures_when_enabled(private_client):
    client, login, _ = private_client
    headers = login("alice")
    with client.app.state.auth_engine.begin() as db:
        db.execute(
            text('INSERT INTO neon_auth."user" VALUES (:id, :name, :email, :verified)'),
            [
                {
                    "id": "fixture",
                    "name": "Nadia Test",
                    "email": "nadia@seed.shonchoy.test",
                    "verified": False,
                },
                {
                    "id": "other",
                    "name": "Nadia Other",
                    "email": "other@seed.shonchoy.test",
                    "verified": False,
                },
                {
                    "id": "outside",
                    "name": "Nadia Outside",
                    "email": "nadia@example.test",
                    "verified": False,
                },
            ],
        )

    def search():
        return client.get("/v1/core/user-directory", params={"q": "nadia"}, headers=headers).json()[
            "data"
        ]["items"]

    assert search() == []
    client.app.state.settings.directory_test_user_ids = ["fixture", "outside"]
    assert [user["id"] for user in search()] == ["fixture"]


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
