from alembic import context
from jpgrader.app_logger import get_logger
from sqlalchemy import engine_from_config, pool

from settings import DB_URL

# Logger
logger = get_logger(__name__)

# Alembic config object
config = context.config
config.set_main_option("sqlalchemy.url", DB_URL)

# Model's metadata
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in offline mode.

    This configures the context with just a URL and not an Engine, though an Engine is
    acceptable here as well.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode.

    In this scenario it is necessary to create an Engine and associate a connection
    with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
