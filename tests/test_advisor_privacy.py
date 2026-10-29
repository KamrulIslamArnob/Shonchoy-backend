import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from fintrack_advisor.config import ProviderSettings, Settings
from fintrack_advisor.main import create_app
from fintrack_advisor.privacy import Capability, model_prompt


@pytest.mark.parametrize("capability", list(Capability))
def test_provider_prompt_is_selected_only_from_fixed_generic_text(capability: Capability) -> None:
    prompt = model_prompt(capability)
    assert prompt
    assert not any(char.isdigit() for char in prompt)
    assert "Alice" not in prompt


def test_user_text_cannot_be_used_as_a_provider_prompt() -> None:
    with pytest.raises(ValueError, match="Unsupported capability"):
        model_prompt("Alice has BDT 12345")  # type: ignore[arg-type]


def test_explanation_endpoint_rejects_user_financial_data() -> None:
    class FakeProvider:
        calls: list[Capability] = []

        async def explain(self, capability: Capability) -> str:
            self.calls.append(capability)
            return "Generic explanation"

    token = "synthetic-test-token-" + "x" * 32
    app = create_app(
        Settings(_env_file=None, dev_api_key=SecretStr(token)),
        ProviderSettings(_env_file=None, provider="disabled"),
    )
    fake = FakeProvider()
    app.state.provider = fake
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        result = client.post(
            "/v1/agent/explanation",
            headers=headers,
            json={"capability": "spending", "amount": 12345, "name": "Alice"},
        )
        assert result.status_code == 422
        assert not fake.calls
        result = client.post(
            "/v1/agent/explanation", headers=headers, json={"capability": "spending"}
        )
        assert result.status_code == 200
        assert fake.calls == [Capability.SPENDING]


def test_provider_settings_read_standard_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FINTRACK_ADVISOR_PROVIDER", "openai")
    monkeypatch.setenv("FINTRACK_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    settings = ProviderSettings(_env_file=None)
    assert settings.provider == "openai"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "synthetic-key"
    assert "synthetic-key" not in repr(settings)
