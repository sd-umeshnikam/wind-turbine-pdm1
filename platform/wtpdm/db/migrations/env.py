from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from wtpdm.db.models import Base
from wtpdm.settings import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata

# Indexes created by raw SQL in migrations (TimescaleDB's own time indexes and our
# per-turbine time indexes) are not in the ORM metadata; keep autogenerate from
# proposing to drop them.
SQL_MANAGED_INDEXES = {
    "telemetry_ts_idx",
    "health_score_ts_idx",
    "ix_telemetry_turbine_ts",
    "ix_health_turbine_ts",
}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and name in SQL_MANAGED_INDEXES)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
