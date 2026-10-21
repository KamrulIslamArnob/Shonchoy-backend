from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINTRACK_ADVISOR_", env_file=".env.advisor", extra="ignore"
    )
    dev_api_key: SecretStr | None = None
