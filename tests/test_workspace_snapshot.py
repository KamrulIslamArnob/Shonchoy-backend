from datetime import date
from uuid import uuid4

from conftest import AUTH
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m
from fintrack_core.finance.persistence import DEV_SCOPE
from fintrack_core.finance.scenarios import seed_scenarios


def test_snapshot_is_authenticated_and_empty_workspace_can_onboard(client):
    assert client.get("/v1/core/workspace-snapshot").status_code == 401
    response = client.get("/v1/core/workspace-snapshot", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"]["profile"]["onboarded"] is False
    assert response.json()["data"]["accounts"] == []


def test_snapshot_contains_observations_and_never_crosses_scope(client):
    other = uuid4()
    with Session(client.app.state.engine) as db, db.begin():
        db.add_all([m.Workspace(id=DEV_SCOPE), m.Workspace(id=other)])
        db.flush()
        db.add(m.Account(scope_id=other, name="Other workspace", kind="cash", currency="BDT"))
        seed_scenarios(db, date(2024, 3, 2))
    response = client.get("/v1/core/workspace-snapshot", headers=AUTH)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["accounts"]) == 19
    assert all(item["name"] != "Other workspace" for item in data["accounts"])
    assert len(data["observations"]) > 100
    assert any(item["deleted"] for item in data["transactions"])


def test_snapshot_fails_closed_instead_of_truncating_large_collections(client):
    with Session(client.app.state.engine) as db, db.begin():
        db.add(m.Workspace(id=DEV_SCOPE))
        db.flush()
        db.add_all([m.Group(scope_id=DEV_SCOPE, name=f"Group {i}") for i in range(1001)])
    assert client.get("/v1/core/workspace-snapshot", headers=AUTH).status_code == 422
