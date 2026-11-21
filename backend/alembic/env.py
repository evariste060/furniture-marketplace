from sqlalchemy import create_engine, pool

from alembic import context
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

# Import approved models here after data-model review.
target_metadata = Base.metadata
# Migrations run as the schema-owner role (MIGRATION_DATABASE_URL, falling back to DATABASE_URL),
# never as the least-privilege runtime role.
url = get_settings().alembic_database_url
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(
        url,
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
