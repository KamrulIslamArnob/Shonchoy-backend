from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from fintrack_core.config import Settings
from fintrack_core.main import create_app
from fintrack_core.models import Base

TOKEN = "synthetic-test-token-" + "x" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, dev_api_key=SecretStr(TOKEN)))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        app.state.engine = engine
        yield test_client
    engine.dispose()
