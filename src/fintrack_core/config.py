from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINTRACK_", env_file=".env", extra="ignore")
    dev_api_key: SecretStr | None = None
    feedback_admin_key: SecretStr | None = None
    database_url: SecretStr | None = None
    auth_database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    neon_auth_url: str | None = None
    command_fingerprint_key: SecretStr | None = None
    enable_development_routes: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
