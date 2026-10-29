from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINTRACK_ADVISOR_", env_file=".env.advisor", extra="ignore"
    )
    dev_api_key: SecretStr | None = None


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINTRACK_ADVISOR_", env_file=".env.advisor", extra="ignore"
    )
    provider: Literal["disabled", "openai", "anthropic"] = "disabled"
    model: str = ""
    base_url: str | None = None
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
