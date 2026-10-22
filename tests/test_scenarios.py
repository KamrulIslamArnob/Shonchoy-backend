from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from fintrack_core.finance import models as m
from fintrack_core.finance.persistence import DEV_SCOPE
from fintrack_core.finance.scenarios import START, seed_scenarios
from fintrack_core.models import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(m.Workspace(id=DEV_SCOPE, name="Preserve this profile", onboarded=True))
        session.commit()
        yield session
    engine.dispose()


def test_repeatable_seed_preserves_existing_records_and_other_scopes(db):
    other = uuid4()
    db.add(m.Workspace(id=other))
    db.flush()
    existing = m.Account(
        scope_id=DEV_SCOPE,
        name="Existing account",
        kind="cash",
        currency="BDT",
        balance_minor=12345,
    )
    foreign = m.Account(
        scope_id=other, name="Other workspace", kind="cash", currency="BDT", balance_minor=98765
    )
    db.add_all([existing, foreign])
    db.flush()
    first = seed_scenarios(db, date(2024, 3, 2))
    second = seed_scenarios(db, date(2024, 3, 2))
    assert first["core_accounts"] == 19
    assert sum(second.values()) == 0
    assert existing.balance_minor == 12345
    assert foreign.balance_minor == 98765
    assert db.get(m.Workspace, DEV_SCOPE).name == "Preserve this profile"
    assert (
        db.scalar(select(func.count()).select_from(m.Account).where(m.Account.scope_id == other))
        == 1
    )


def test_seed_has_valid_transfers_splits_edge_cases_and_history(db):
    seed_scenarios(db, date(2026, 10, 23))
    rows = list(db.scalars(select(m.Transaction)))
    assert all(isinstance(t.amount_minor, int) and t.amount_minor > 0 for t in rows)
    pairs = {}
    for item in rows:
        if item.transfer_pair_id:
            pairs.setdefault(item.transfer_pair_id, []).append(item)
        if item.splits:
            assert sum(split["amount_minor"] for split in item.splits) == item.amount_minor
    assert pairs
    for pair in pairs.values():
        assert len(pair) == 2
        assert {t.direction for t in pair} == {"in", "out"}
        assert len({t.account_id for t in pair}) == 2
        assert pair[0].amount_minor == pair[1].amount_minor
    assert any(t.amount_minor == 1 for t in rows)
    assert any(t.pending for t in rows) and any(t.hidden for t in rows)
    assert any(t.deleted for t in rows) and any(not t.reviewed for t in rows)
    assert any(t.kind == "expense" and t.direction == "in" for t in rows)
    assert any(t.kind == "income" and t.direction == "out" for t in rows)
    assert not any(t.booked_on.strftime("%Y-%m") == "2024-07" for t in rows)
    assert any(t.booked_on == date(2024, 2, 29) for t in rows)
    accounts = {a.id: a for a in db.scalars(select(m.Account))}
    assert len({a.kind for a in accounts.values()}) == 15
    observations = list(db.scalars(select(m.Observation)))
    start_net = sum(
        (1 if accounts[o.account_id].is_asset else -1) * o.amount_minor
        for o in observations
        if o.effective_on == START
    )
    end_net = sum(
        (1 if accounts[o.account_id].is_asset else -1) * o.amount_minor
        for o in observations
        if o.effective_on == date(2026, 10, 23)
    )
    assert start_net < 0 < end_net
    for item in observations:
        if item.effective_on == date(2026, 10, 23):
            assert item.amount_minor == accounts[item.account_id].balance_minor


def test_budget_backfill_preserves_current_allocations_and_rolls_back(db):
    current = [{"from_month": "2026-09", "lines": {}}]
    budget = m.Budget(
        scope_id=DEV_SCOPE,
        currency="BDT",
        income_minor=100,
        savings_minor=50,
        versions=current,
        overrides={},
        rollover={},
    )
    db.add(budget)
    db.commit()
    seed_scenarios(db, date(2024, 3, 2))
    db.refresh(budget)
    assert budget.versions[-1] == current[0]
    assert budget.versions[0]["from_month"] == "2024-01"
    assert budget.income_minor == 100 and budget.savings_minor == 50
    db.rollback()
    assert db.scalar(select(func.count()).select_from(m.Account)) == 0
    db.refresh(budget)
    assert budget.versions == current


def test_seed_denies_missing_scope_and_unbounded_dates(db):
    with pytest.raises(ValueError, match="workspace"):
        seed_scenarios(db, date(2026, 10, 23), uuid4())
    with pytest.raises(ValueError, match="between"):
        seed_scenarios(db, date(2100, 1, 1))
