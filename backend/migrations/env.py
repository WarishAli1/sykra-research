from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.config import settings
from app.db.models import Base

config = context.config
MIGRATION_URL = settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", MIGRATION_URL)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=MIGRATION_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
