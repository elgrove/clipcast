import logging
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger("clipcast")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 60},
    echo=settings.debug,
    pool_pre_ping=True,
)


def init_db() -> None:
    import app.models  # noqa: F401 — ensure all models are registered

    SQLModel.metadata.create_all(engine)
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
