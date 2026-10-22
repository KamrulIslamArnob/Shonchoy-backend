from uuid import uuid4

from conftest import AUTH
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PUBLIC = "/v1/core/feedback"
ADMIN = "/v1/admin/feedback"
ADMIN_TOKEN = "synthetic-feedback-admin-" + "z" * 32
ADMIN_AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def admin(client):
    client.app.state.settings.feedback_admin_key = SecretStr(ADMIN_TOKEN)
    return ADMIN_AUTH


def send(client, path, body, *, auth=AUTH, key=None, method="post", version=None):
    headers = {**auth, "Idempotency-Key": key or str(uuid4())}
    if version is not None:
        headers["If-Match"] = f'"{version}"'
    return getattr(client, method)(path, json=body, headers=headers)


def test_interest_is_explicit_deduplicated_and_private(client):
    response = client.get(PUBLIC + "/context?feature=partner", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"] == {"interested": False, "categories": []}
    assert client.get(ADMIN + "/entries", headers=AUTH).status_code in (401, 503)
    key = str(uuid4())
    body = {"featureKey": "partner", "segment": "household", "source": "settings.partner"}
    first = send(client, PUBLIC + "/interest", body, key=key)
    assert first.status_code == 201, first.text
    assert send(client, PUBLIC + "/interest", body, key=key).json()["data"] == first.json()["data"]
    assert (
        send(client, PUBLIC + "/interest", body).json()["data"]["id"] == first.json()["data"]["id"]
    )
    assert client.get(PUBLIC + "/context?feature=partner", headers=AUTH).json()["data"][
        "interested"
    ]
    stats = client.get(ADMIN + "/summary", headers=admin(client)).json()["data"]
    assert stats["interestCount"] == 1
    assert stats["feedbackCount"] == 0
    assert client.get(PUBLIC + "/entries", headers=AUTH).status_code == 405


def test_feedback_categories_filters_concurrency_and_history(client):
    auth = admin(client)
    created = send(
        client, ADMIN + "/categories", {"name": "Suggestions", "featureKey": "partner"}, auth=auth
    )
    assert created.status_code == 201, created.text
    category = created.json()["data"]
    context = client.get(PUBLIC + "/context?feature=partner", headers=AUTH).json()["data"]
    assert context["categories"][0]["name"] == "Suggestions"
    body = {
        "featureKey": "partner",
        "segment": "household",
        "source": "settings.partner",
        "categoryId": category["id"],
        "message": "  Synthetic suggestion: shared budgets.  ",
    }
    key = str(uuid4())
    first = send(client, PUBLIC + "/entries", body, key=key)
    assert first.status_code == 201, first.text
    assert set(first.json()["data"]) == {"id", "createdAt"}
    assert send(client, PUBLIC + "/entries", body, key=key).json()["data"] == first.json()["data"]
    assert (
        send(client, PUBLIC + "/entries", {**body, "message": "Different"}, key=key).status_code
        == 409
    )
    rows = client.get(
        ADMIN + "/entries?feature=partner&segment=household&limit=1", headers=auth
    ).json()["data"]
    assert len(rows["items"]) == 1
    assert rows["items"][0]["message"] == "Synthetic suggestion: shared budgets."
    assert rows["items"][0]["source"] == "settings.partner"
    assert rows["items"][0]["subjectRef"]
    assert (
        client.get(ADMIN + "/entries?feature=unknown", headers=auth).json()["data"]["items"] == []
    )
    update = {"name": "Ideas", "archived": True}
    assert (
        send(
            client, ADMIN + f"/categories/{category['id']}", update, auth=auth, method="patch"
        ).status_code
        == 428
    )
    assert (
        send(
            client,
            ADMIN + f"/categories/{category['id']}",
            update,
            auth=auth,
            method="patch",
            version=1,
        ).status_code
        == 200
    )
    assert (
        send(
            client,
            ADMIN + f"/categories/{category['id']}",
            update,
            auth=auth,
            method="patch",
            version=1,
        ).status_code
        == 409
    )
    assert (
        client.get(PUBLIC + "/context?feature=partner", headers=AUTH).json()["data"]["categories"]
        == []
    )
    assert send(client, PUBLIC + "/entries", body).status_code == 422
    assert (
        client.get(ADMIN + "/entries", headers=auth).json()["data"]["items"][0]["categoryId"]
        == category["id"]
    )


def test_feedback_rejects_authority_invalid_inputs_and_cross_feature_categories(client):
    assert client.get(PUBLIC + "/context?feature=partner").status_code == 401
    auth = admin(client)
    assert client.get(ADMIN + "/entries", headers=AUTH).status_code == 401
    assert send(client, ADMIN + "/categories", {"name": "Ideas"}).status_code == 401
    cat = send(
        client, ADMIN + "/categories", {"name": "Other", "featureKey": "accounts"}, auth=auth
    ).json()["data"]
    base = {
        "featureKey": "partner",
        "segment": "household",
        "source": "settings.partner",
        "message": "Synthetic suggestion",
    }
    for patch in (
        {"message": " "},
        {"message": "x" * 4001},
        {"subjectRef": "forged"},
        {"categoryId": cat["id"]},
        {"categoryId": str(uuid4())},
        {"source": "https://untrusted.example/private"},
    ):
        assert send(client, PUBLIC + "/entries", {**base, **patch}).status_code == 422
    assert (
        send(
            client, ADMIN + "/categories", {"name": "other", "featureKey": "accounts"}, auth=auth
        ).status_code
        == 409
    )


def test_feedback_pagination(client):
    from fintrack_core.feedback.models import FeedbackEntry

    auth = admin(client)
    body = {
        "featureKey": "partner",
        "segment": "household",
        "source": "settings.partner",
        "message": "Synthetic suggestion",
    }
    for _ in range(3):
        assert send(client, PUBLIC + "/entries", body).status_code == 201
    page = client.get(ADMIN + "/entries?limit=2", headers=auth).json()["data"]
    assert len(page["items"]) == 2
    following = client.get(
        ADMIN + "/entries?limit=2&cursor=" + page["nextCursor"], headers=auth
    ).json()["data"]
    assert len(following["items"]) == 1
    assert not ({row["id"] for row in page["items"]} & {row["id"] for row in following["items"]})
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(FeedbackEntry)) == 3


def test_feedback_failure_rolls_back_and_same_key_can_retry(client):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    from fintrack_core.feedback.models import FeedbackEntry

    body = {
        "featureKey": "partner",
        "segment": "household",
        "source": "settings.partner",
        "message": "Synthetic retry",
    }
    key = str(uuid4())

    def unavailable(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO core_outbox"):
            raise OperationalError("synthetic outage", {}, Exception("synthetic"))

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        failed = send(client, PUBLIC + "/entries", body, key=key)
        assert failed.status_code == 503
        assert body["message"] not in failed.text
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(FeedbackEntry)) == 0
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    assert send(client, PUBLIC + "/entries", body, key=key).status_code == 201


def test_category_changes_record_signed_actor_and_hash_chain_atomically(client):
    import hashlib
    import json

    from fintrack_core.feedback.models import FeedbackCategoryChange

    auth = {**admin(client), "X-Feedback-Actor": "synthetic-admin-86"}
    category = send(client, ADMIN + "/categories", {"name": "Ideas"}, auth=auth).json()["data"]
    assert (
        send(
            client,
            ADMIN + f"/categories/{category['id']}",
            {"name": "Ideas", "archived": True},
            auth=auth,
            method="patch",
            version=1,
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        rows = list(
            db.scalars(select(FeedbackCategoryChange).order_by(FeedbackCategoryChange.created_at))
        )
        assert len(rows) == 2
        assert rows[0].actor_id == rows[1].actor_id == "synthetic-admin-86"
        assert rows[0].previous_hash == "0" * 64
        assert rows[1].previous_hash == rows[0].hash
        assert rows[0].before is None
        assert rows[1].before["archived"] is False
        assert rows[1].after["archived"] is True
        value = json.dumps(
            [
                str(rows[1].id),
                rows[1].actor_id,
                str(rows[1].category_id),
                rows[1].before,
                rows[1].after,
                rows[1].previous_hash,
                "local-admin-proxy",
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        assert rows[1].hash == hashlib.sha256(value.encode()).hexdigest()
