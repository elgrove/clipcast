import logging
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings

logger = logging.getLogger("clipcast")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 60},
    echo=settings.debug,
    pool_pre_ping=True,
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.commit()
    _run_migrations()
    logger.info("Database initialised")
    _seed_preset_models()


def _run_migrations() -> None:
    with engine.connect() as conn:
        # Add stored_filename column if it doesn't exist
        ep_columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(podcast_episodes)").fetchall()
        ]
        if "stored_filename" not in ep_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_episodes ADD COLUMN stored_filename VARCHAR(500) DEFAULT ''"
            )
            conn.commit()
            logger.info("Added stored_filename column to podcast_episodes")
            _backfill_stored_filenames()

        if "cleaned_at" not in ep_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_episodes ADD COLUMN cleaned_at TIMESTAMP DEFAULT NULL"
            )
            conn.commit()
            logger.info("Added cleaned_at column to podcast_episodes")

        show_columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(podcast_shows)").fetchall()
        ]
        if "custom_prompt" not in show_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_shows ADD COLUMN custom_prompt TEXT DEFAULT ''"
            )
            conn.commit()
            logger.info("Added custom_prompt column to podcast_shows")

        if "cleanup_keep_days" not in show_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_shows ADD COLUMN cleanup_keep_days INTEGER DEFAULT NULL"
            )
            conn.exec_driver_sql(
                "ALTER TABLE podcast_shows ADD COLUMN cleanup_keep_count INTEGER DEFAULT NULL"
            )
            conn.commit()
            logger.info("Added cleanup columns to podcast_shows")


def _backfill_stored_filenames() -> None:
    from app.models import PodcastEpisode

    with Session(engine) as session:
        episodes = session.exec(select(PodcastEpisode)).all()
        count = 0
        for episode in episodes:
            if episode.stored_filename:
                continue
            # Check if a file exists on disk with the generated filename
            generated = episode._generate_base_filename()
            try:
                directory = episode.podcast.directory
            except Exception:
                continue
            if (directory / f"{generated}.mp3").exists():
                episode.stored_filename = generated
                session.add(episode)
                count += 1
            else:
                # Search for any matching file by date prefix
                date_prefix = generated.split("_")[0]
                for f in directory.iterdir() if directory.exists() else []:
                    if f.name.startswith(date_prefix) and f.name.endswith(".mp3") and not f.name.endswith(".raw"):
                        episode.stored_filename = f.stem
                        session.add(episode)
                        count += 1
                        break
        session.commit()
        if count:
            logger.info("Backfilled stored_filename for %d episodes", count)


def _seed_preset_models() -> None:
    from app.models import PRESET_MODELS, AIModel

    with Session(engine) as session:
        for name, info in PRESET_MODELS.items():
            existing = session.exec(select(AIModel).where(AIModel.name == name)).first()
            if not existing:
                model = AIModel(
                    name=name,
                    provider=info["provider"].value,
                    is_preset=True,
                )
                session.add(model)
                logger.info(f"Seeded preset model: {name}")
        session.commit()

    # Ensure config singleton exists
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
