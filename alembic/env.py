from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from alembic import context
from fintrack_core.config import Settings
from fintrack_core.database import postgres_url
from fintrack_core.feedback import models as feedback_models

target_metadata = feedback_models.FeedbackCategory.metadata

settings = Settings()
raw_url = settings.migration_database_url
if raw_url is None or not raw_url.get_secret_value():
    raise RuntimeError("FINTRACK_MIGRATION_DATABASE_URL is required for migrations.")
url = postgres_url(raw_url.get_secret_value())
if url.host and "-pooler." in url.host:
    raise RuntimeError("Migrations require the direct Neon URL, without -pooler.")

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table="fintrack_dev_alembic_version",
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(
        url, poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table="fintrack_dev_alembic_version",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
