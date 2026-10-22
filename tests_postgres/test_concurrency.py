"""Independent processes and SQL sessions; never use production or default workspace data."""

import multiprocessing
import subprocess
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from fintrack_core.config import Settings
from fintrack_core.database import build_engine, postgres_url
from fintrack_core.finance import models as m
from fintrack_core.finance.application import accounts, catalog, planning
from fintrack_core.finance.domain import DomainError
from fintrack_core.finance.persistence import SqlUnitOfWork


def run_command(scope, key, operation, payload):
    engine = None
    try:
        settings = Settings()
        engine = build_engine(settings.database_url.get_secret_value())
        with Session(engine) as db:
            uow = SqlUnitOfWork(db, settings.dev_api_key.get_secret_value(), UUID(scope))
            actions = {
                "create": lambda r: accounts.create(r, payload),
                "edit": lambda r: accounts.edit(r, payload["id"], payload["changes"]),
                "category": lambda r: catalog.category(r, payload),
                "budget": lambda r: planning.create_budget(r, "2026-10", payload),
                "line": lambda r: planning.line(r, payload["month"], payload["changes"]),
            }
            return {"status": 200, "data": uow.command(key, operation, payload, actions[operation])}
    except DomainError as error:
        return {"status": error.status}
    except SQLAlchemyError:
        return {"status": 503}
    except Exception as error:
        return {"status": 500, "errorType": type(error).__name__}
    finally:
        if engine:
            engine.dispose()


def process_command(barrier, queue, arguments, index):
    try:
        barrier.wait(timeout=30)
        queue.put((index, run_command(*arguments)))
    except Exception as error:
        queue.put((index, {"status": 500, "errorType": type(error).__name__}))


def concurrent(commands):
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(len(commands)), context.Queue()
    processes = [
        context.Process(target=process_command, args=(barrier, queue, args, index))
        for index, args in enumerate(commands)
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=90) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        return [result for _, result in sorted(results)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


@pytest.fixture(scope="session")
def engine():
    settings = Settings()
    assert settings.database_url and settings.dev_api_key, (
        "Configure development credentials privately."
    )
    lookup = subprocess.run(
        [
            "npx",
            "--yes",
            "neon@8.8.0",
            "connection-string",
            "br-calm-truth-b4ghgt7x",
            "--project-id",
            "winter-surf-88756036",
            "--pooled",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert lookup.returncode == 0, "Cannot verify development target; authenticate Neon CLI."
    expected, actual = (
        postgres_url(lookup.stdout.strip()),
        postgres_url(settings.database_url.get_secret_value()),
    )
    assert (expected.host, expected.database) == (actual.host, actual.database), (
        "Development target mismatch."
    )
    result = build_engine(settings.database_url.get_secret_value())
    try:
        yield result
    finally:
        result.dispose()


@pytest.fixture
def scope(engine):
    identifier = str(uuid4())
    yield identifier
    with engine.begin() as connection:
        for table in reversed(m.Workspace.metadata.sorted_tables):
            if table.name.startswith("core_"):
                column = table.c.id if table.name == "core_workspaces" else table.c.scope_id
                connection.execute(delete(table).where(column == UUID(identifier)))


def cash(name="Synthetic process cash"):
    return {
        "name": name,
        "kind": "cash",
        "currency": "BDT",
        "institution": "Manual",
        "is_asset": True,
        "balance_minor": 100,
        "debit_card_last4": None,
    }


def scoped_count(engine, scope, model):
    with Session(engine) as db:
        return db.scalar(
            select(func.count()).select_from(model).where(model.scope_id == UUID(scope))
        )


def test_same_key_across_four_processes_has_one_atomic_effect(engine, scope):
    key = str(uuid4())
    args = (scope, key, "create", cash())
    results = concurrent([args] * 4)
    assert all(result["status"] in {200, 503} for result in results)
    # A bounded lock timeout is retryable with the same key; it never permits another effect.
    if any(result["status"] == 503 for result in results):
        results.append(run_command(*args))
    successful = [r for r in results if r["status"] == 200]
    assert successful and len({r["data"]["id"] for r in successful}) == 1
    for model in (m.Account, m.Observation, m.Idempotency, m.Audit, m.Outbox):
        assert scoped_count(engine, scope, model) == 1
    assert run_command(scope, key, "create", cash("Different"))["status"] == 409


def test_two_process_edit_has_one_winner_and_one_conflict(engine, scope):
    created = run_command(scope, str(uuid4()), "create", cash())["data"]
    commands = [
        (
            scope,
            str(uuid4()),
            "edit",
            {"id": created["id"], "changes": {"expected_version": 1, "name": name}},
        )
        for name in ["First edit", "Second edit"]
    ]
    results = concurrent(commands)
    for index, result in enumerate(results):
        if result["status"] == 503:
            # Complete any transient timeout through a fresh request, never a different key.
            result.update(run_command(*commands[index]))
    assert sorted(r["status"] for r in results) == [200, 409]
    with Session(engine) as db:
        account = db.get(m.Account, UUID(created["id"]))
        assert account.version == 2 and account.name in {"First edit", "Second edit"}
    assert scoped_count(engine, scope, m.Audit) == 2


def test_budget_edits_use_one_versioned_aggregate(engine, scope):
    cat = run_command(
        scope,
        str(uuid4()),
        "category",
        {
            "name": "Synthetic",
            "kind": "expense",
            "group_id": None,
            "color": "#718096",
            "icon": "tag",
        },
    )["data"]
    run_command(
        scope,
        str(uuid4()),
        "budget",
        {"currency": "BDT", "income_minor": 1000, "savings_minor": 0, "lines": {cat["id"]: 100}},
    )
    commands = [
        (
            scope,
            str(uuid4()),
            "line",
            {
                "month": "2026-11",
                "changes": {
                    "currency": "BDT",
                    "category_id": cat["id"],
                    "expected_version": 1,
                    "amount_minor": amount,
                    "apply_future": future,
                },
            },
        )
        for amount, future in [(200, False), (300, True)]
    ]
    results = concurrent(commands)
    for index, result in enumerate(results):
        if result["status"] == 503:
            result.update(run_command(*commands[index]))
    assert sorted(r["status"] for r in results) == [200, 409]
    with Session(engine) as db:
        budget = db.scalar(select(m.Budget).where(m.Budget.scope_id == UUID(scope)))
        assert budget.version == 2
        assert bool(budget.overrides) != (len(budget.versions) == 2)


def test_postgres_outbox_failure_rolls_back_and_retry_works(engine, scope):
    def reject(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO core_outbox"):
            raise OperationalError("synthetic", {}, Exception("synthetic"))

    settings = Settings()
    key = str(uuid4())
    event.listen(engine, "before_cursor_execute", reject)
    try:
        with Session(engine) as db, pytest.raises(SQLAlchemyError):
            SqlUnitOfWork(db, settings.dev_api_key.get_secret_value(), UUID(scope)).command(
                key, "create", cash(), lambda r: accounts.create(r, cash())
            )
    finally:
        event.remove(engine, "before_cursor_execute", reject)
    for model in (m.Account, m.Idempotency, m.Audit, m.Outbox):
        assert scoped_count(engine, scope, model) == 0
    assert run_command(scope, key, "create", cash())["status"] == 200


def test_different_server_scopes_cannot_read_guessed_ids(engine, scope):
    created = run_command(scope, str(uuid4()), "create", cash())["data"]
    settings = Settings()
    with Session(engine) as db:
        uow = SqlUnitOfWork(db, settings.dev_api_key.get_secret_value(), uuid4())
        with pytest.raises(DomainError) as error:
            uow.read(lambda r: r.accounts.get(created["id"]))
        assert error.value.status == 404


def test_live_api_transaction_budget_report_journey(engine, scope):
    from fastapi.testclient import TestClient

    from fintrack_core.main import create_app

    settings = Settings()
    app = create_app(settings)
    app.state.core_scope_id = scope
    app.state.core_uow_factory = lambda db: SqlUnitOfWork(
        db, settings.dev_api_key.get_secret_value(), UUID(scope)
    )
    auth = {"Authorization": "Bearer " + settings.dev_api_key.get_secret_value()}
    with TestClient(app) as client:

        def post(path, payload, method="post", expected=201):
            response = getattr(client, method)(
                "/v1/core" + path, json=payload, headers={**auth, "Idempotency-Key": str(uuid4())}
            )
            assert response.status_code == expected, (
                "Live API command failed (response is sanitized)."
            )
            return response.json()["data"]

        account = post("/accounts", {"name": "Synthetic live account", "balanceMinor": 100000})
        category = post("/categories", {"name": "Synthetic live category"})
        post(
            "/transactions",
            {
                "accountId": account["id"],
                "merchant": "Synthetic live expense",
                "amountMinor": 1000,
                "bookedOn": "2026-10-20",
                "categoryId": category["id"],
            },
        )
        post(
            "/transactions",
            {
                "accountId": account["id"],
                "merchant": "Synthetic live refund",
                "amountMinor": 200,
                "direction": "in",
                "bookedOn": "2026-10-20",
                "categoryId": category["id"],
            },
        )
        post(
            "/budgets/2026-10",
            {"incomeMinor": 10000, "savingsMinor": 0, "lines": {category["id"]: 2000}},
            method="put",
        )
        report = client.get("/v1/core/dashboard/summary?selected=2026-10", headers=auth)
        assert report.status_code == 200
        assert report.json()["data"]["cashflow"]["expenseMinor"] == 800
        assert report.json()["data"]["assetsMinor"] == 100000
        budget = client.get("/v1/core/budgets/2026-10", headers=auth)
        assert budget.status_code == 200
        assert budget.json()["data"]["rows"][0]["spentMinor"] == 800
