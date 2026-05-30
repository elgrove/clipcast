import logging
from collections.abc import Generator
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from alembic import command
from app.config import settings

logger = logging.getLogger("clipcast")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 60},
    echo=settings.debug,
    pool_pre_ping=True,
)

ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_INI_PATH.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def apply_migrations() -> None:
    import app.models  # noqa: F401 — ensure models are imported before alembic touches metadata

    cfg = _alembic_config()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "alembic_version" not in table_names and "podcast_shows" in table_names:
        logger.info("Existing database without alembic_version — stamping baseline")
        command.stamp(cfg, "head")
        return

    command.upgrade(cfg, "head")
    logger.info("Database migrations applied")


def _check_schema_drift() -> None:
    """Compare the live DB schema against `SQLModel.metadata` and log at
    ERROR level if they diverge.

    The expected post-`alembic upgrade head` state is zero diff. A non-empty
    diff means a model change merged without a paired migration (see
    `Working with Alembic` in CLAUDE.md). The app is still allowed to boot
    so the operator can inspect; the broken queries will surface as ORM
    errors with the column / table name attached."""
    import app.models  # noqa: F401 — ensure metadata is populated

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, SQLModel.metadata)

    if diff:
        logger.error(
            "Schema drift after `alembic upgrade head` — live DB does not "
            "match SQLModel.metadata. Most likely a schema-affecting model "
            "change merged without a paired migration. Generate one with "
            "`uv run alembic revision --autogenerate -m '...'`. Diff: %r",
            diff,
        )


def init_db() -> None:
    apply_migrations()
    _check_schema_drift()
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.commit()
    logger.info("Database initialised")
    _ensure_default_config()


def _ensure_default_config() -> None:
    from app.models import AppConfig

    with Session(engine) as session:
        config = session.get(AppConfig, "config")
        if not config:
            session.add(AppConfig(id="config"))
            session.commit()
            logger.info("Created default config")


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
