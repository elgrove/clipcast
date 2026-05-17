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
    import app.models  # noqa: F401 — ensure all models are registered

    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.commit()
    _run_migrations()
    logger.info("Database initialised")
    _seed_preset_models()


def _run_migrations() -> None:
    with engine.connect() as conn:
        # Skip migrations if tables were just created (fresh install)
        tables = [
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        if "podcast_episodes" not in tables:
            return

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

        if "cut_regions" not in ep_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_episodes ADD COLUMN cut_regions TEXT DEFAULT '[]'"
            )
            conn.commit()
            logger.info("Added cut_regions column to podcast_episodes")
            _backfill_cut_regions()

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

        if "clip_mode" not in show_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_shows ADD COLUMN clip_mode VARCHAR(10) DEFAULT 'ai'"
            )
            conn.exec_driver_sql(
                "UPDATE podcast_shows SET clip_mode = CASE WHEN has_ads THEN 'ai' ELSE 'off' END"
                " WHERE clip_mode = 'ai'"
            )
            conn.commit()
            logger.info("Added clip_mode column to podcast_shows and backfilled from has_ads")

        if "verify_acast_host_read_ads" not in show_columns:
            conn.exec_driver_sql(
                "ALTER TABLE podcast_shows ADD COLUMN verify_acast_host_read_ads BOOLEAN DEFAULT 0"
            )
            conn.commit()
            logger.info("Added verify_acast_host_read_ads column to podcast_shows")

        config_columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(config)").fetchall()
        ]
        if "identify_ads_in_acast_breaks" not in config_columns:
            conn.exec_driver_sql(
                "ALTER TABLE config ADD COLUMN identify_ads_in_acast_breaks BOOLEAN DEFAULT 0"
            )
            conn.commit()
            logger.info("Added identify_ads_in_acast_breaks column to config")


def _backfill_cut_regions() -> None:
    """Move existing ad data onto the new `cut_regions` field.

    Acast bracket markers stop being "ads" — they're just cut spans, so they
    move from `ads` to `cut_regions`. AI-identified ads stay in `ads` and are
    also mirrored into `cut_regions` so the editor cuts them."""
    import json

    from app.models import ACAST_ADVERT_LABEL, CutRegion, PodcastEpisode

    with Session(engine) as session:
        episodes = session.exec(select(PodcastEpisode)).all()
        count = 0
        for episode in episodes:
            if episode.cut_regions_json and episode.cut_regions_json != "[]":
                continue
            raw_ads = json.loads(episode.ads_json or "[]")
            if not raw_ads:
                continue
            remaining_ads = []
            regions: list[CutRegion] = []
            for ad in raw_ads:
                label = ad.get("advert_for") or ""
                region = CutRegion(
                    start_time=ad["start_time"],
                    end_time=ad["end_time"],
                    label=label or "Ad",
                )
                regions.append(region)
                if label != ACAST_ADVERT_LABEL:
                    remaining_ads.append(ad)
            episode.cut_regions = regions
            episode.ads_json = json.dumps(remaining_ads)
            session.add(episode)
            count += 1
        session.commit()
        if count:
            logger.info("Backfilled cut_regions for %d episodes", count)


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
                    if (
                        f.name.startswith(date_prefix)
                        and f.name.endswith(".mp3")
                        and not f.name.endswith(".raw")
                    ):
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
