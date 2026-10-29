import ast
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from fintrack_advisor.config import Settings
from fintrack_advisor.main import create_app

TOKEN = "synthetic-advisor-token-" + "x" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_private_analysis_rejects_identity_and_invalid_financial_fields():
    body = {
        "schemaVersion": 1,
        "intent": "cashflow",
        "currency": "BDT",
        "month": "2026-10",
        "values": {"incomeMinor": 20000, "expenseMinor": 25000},
    }
    with TestClient(create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))) as client:
        assert client.post("/v1/agent/analysis", json=body).status_code == 401
        response = client.post("/v1/agent/analysis", headers=AUTH, json=body)
        assert response.status_code == 200
        assert (
            response.json()["data"]["answer"]
            == "Your recorded cash flow for 2026-10 is -BDT 50.00."
        )
        assert (
            client.post(
                "/v1/agent/analysis", headers=AUTH, json={**body, "name": "Alice"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/agent/analysis", headers=AUTH, json={**body, "values": {"incomeMinor": 20}}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/agent/analysis", headers=AUTH, json={**body, "currency": "ALI"}
            ).status_code
            == 422
        )


def test_graph_routes_tool_and_isolates_requests():
    with TestClient(create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/health/ready", headers=AUTH).status_code == 200
        assert client.post("/v1/agent/runs", json={"message": "hello"}).status_code == 401
        result = client.post(
            "/v1/agent/runs", headers=AUTH, json={"message": "List capabilities"}
        ).json()["data"]
        assert result["mode"] == "offline_stub"
        assert result["steps"] == ["route", "capabilities", "respond"]
        assert "accounts" in result["answer"]
        result = client.post("/v1/agent/runs", headers=AUTH, json={"message": "hello"}).json()[
            "data"
        ]
        assert result["steps"] == ["route", "respond"]
        assert "No model" in result["answer"]
        assert client.post("/v1/agent/runs", headers=AUTH, json={"message": " "}).status_code == 422
        assert (
            client.post("/v1/agent/runs", headers=AUTH, json={"message": "x" * 4001}).status_code
            == 422
        )


def test_missing_advisor_key_denies_and_does_not_load_core_settings(monkeypatch):
    monkeypatch.setenv("FINTRACK_DATABASE_URL", "synthetic-should-not-be-read")
    settings = Settings(_env_file=None)
    assert set(type(settings).model_fields) == {"dev_api_key"}
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/agent/runs", json={"message": "hello"}).status_code == 503
    for source in (Path(__file__).parents[1] / "src" / "fintrack_advisor").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("fintrack_core", "sqlalchemy", "psycopg")
                )


def test_graph_failure_and_timeout_are_safe():
    class BrokenGraph:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("synthetic-private-prompt")

    class TimedOutGraph:
        async def ainvoke(self, *args, **kwargs):
            raise TimeoutError("synthetic-private-prompt")

    app = create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))
    with TestClient(app) as client:
        for graph, expected in [(BrokenGraph(), 503), (TimedOutGraph(), 504)]:
            app.state.graph = graph
            result = client.post("/v1/agent/runs", headers=AUTH, json={"message": "hello"})
            assert result.status_code == expected
            assert "private" not in result.text


def test_ambient_tracing_is_disabled_for_graph_execution():
    from langsmith import tracing_context
    from langsmith.utils import tracing_is_enabled

    class TracingProbe:
        async def ainvoke(self, *args, **kwargs):
            assert tracing_is_enabled() is False
            return {"answer": "Offline", "steps": ["respond"]}

    app = create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))
    app.state.graph = TracingProbe()
    with tracing_context(enabled=True):
        with TestClient(app) as client:
            result = client.post("/v1/agent/runs", headers=AUTH, json={"message": "Synthetic"})
            assert result.status_code == 200
