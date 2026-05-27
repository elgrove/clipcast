import logging
from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import Session, create_engine

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


def init_db() -> None:
    apply_migrations()
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
