#!/usr/bin/env python3
"""Migrate data from the Django Clipcast database to the new FastAPI schema.

Reads from the old Django SQLite database (read-only) and writes to a new database.
Creates a timestamped backup of the old database before starting.

Usage:
    python scripts/migrate_from_django.py --old-db /data/db.sqlite3 --new-db /data/clipcast.db
    python scripts/migrate_from_django.py --old-db /data/db.sqlite3 --new-db /data/clipcast.db --podcasts-dir /podcasts
"""

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate")


def backup_database(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".backup.{timestamp}")
    shutil.copy2(db_path, backup_path)
    logger.info("Database backed up to %s", backup_path)
    return backup_path


def create_file_manifest(podcasts_dir: Path) -> Path:
    if not podcasts_dir.exists():
        logger.warning("Podcasts directory does not exist: %s", podcasts_dir)
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = podcasts_dir / f"manifest_{timestamp}.txt"

    count = 0
    with open(manifest_path, "w") as f:
        f.write(f"# File manifest created {timestamp}\n")
        f.write(f"# Directory: {podcasts_dir}\n\n")
        for file_path in sorted(podcasts_dir.rglob("*")):
            if file_path.is_file() and file_path.name != manifest_path.name:
                size = file_path.stat().st_size
                md5 = hashlib.md5(file_path.read_bytes()).hexdigest()
                rel = file_path.relative_to(podcasts_dir)
                f.write(f"{md5}  {size:>12}  {rel}\n")
                count += 1

    logger.info("File manifest created: %s (%d files)", manifest_path, count)
    return manifest_path


def migrate(old_db_path: str, new_db_path: str, podcasts_dir: str = None):
    old_path = Path(old_db_path)
    new_path = Path(new_db_path)

    if not old_path.exists():
        logger.error("Old database not found: %s", old_path)
        return

    # Step 1: Backup
    logger.info("=== Step 1: Backup ===")
    backup_database(old_path)

    if podcasts_dir:
        create_file_manifest(Path(podcasts_dir))

    # Step 2: Read old database (read-only)
    logger.info("=== Step 2: Reading old database ===")
    old_conn = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    old_conn.row_factory = sqlite3.Row

    # Step 3: Create new database
    logger.info("=== Step 3: Creating new database ===")
    if new_path.exists():
        logger.error("New database already exists: %s. Remove it first.", new_path)
        old_conn.close()
        return

    new_conn = sqlite3.connect(str(new_path))
    new_conn.execute("PRAGMA journal_mode=WAL")

    _create_tables(new_conn)

    # Step 4: Migrate data
    logger.info("=== Step 4: Migrating data ===")

    # AI Models
    ai_model_count = _migrate_ai_models(old_conn, new_conn)
    logger.info("Migrated %d AI models", ai_model_count)

    # Config
    _migrate_config(old_conn, new_conn)
    logger.info("Migrated config")

    # Podcast Shows
    show_count = _migrate_podcast_shows(old_conn, new_conn)
    logger.info("Migrated %d podcast shows", show_count)

    # Podcast Episodes
    episode_count = _migrate_podcast_episodes(old_conn, new_conn)
    logger.info("Migrated %d podcast episodes", episode_count)

    # Clipping Reports
    report_count = _migrate_clipping_reports(old_conn, new_conn)
    logger.info("Migrated %d clipping reports", report_count)

    new_conn.commit()
    old_conn.close()
    new_conn.close()

    logger.info("=== Migration complete ===")
    logger.info("Old database: %s (untouched)", old_path)
    logger.info("New database: %s", new_path)


def _create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_models (
            id TEXT PRIMARY KEY,
            created_at DATETIME,
            updated_at DATETIME,
            name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            host TEXT DEFAULT '',
            is_preset INTEGER DEFAULT 0,
            input_price REAL DEFAULT 0,
            output_price REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS config (
            id TEXT PRIMARY KEY DEFAULT 'config',
            transcription_model_id TEXT REFERENCES ai_models(id),
            analysis_model_id TEXT REFERENCES ai_models(id),
            gemini_api_key TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS podcast_shows (
            id TEXT PRIMARY KEY,
            created_at DATETIME,
            updated_at DATETIME,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            itunes_id TEXT NOT NULL UNIQUE,
            source_rss_url TEXT NOT NULL,
            path_directory TEXT NOT NULL,
            has_ads INTEGER NOT NULL,
            initial_sync_completed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS podcast_episodes (
            id TEXT PRIMARY KEY,
            created_at DATETIME,
            updated_at DATETIME,
            podcast_id TEXT NOT NULL REFERENCES podcast_shows(id) ON DELETE CASCADE,
            guid TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at DATETIME,
            description TEXT DEFAULT '',
            duration INTEGER,
            source_audio_url TEXT DEFAULT '',
            ads TEXT DEFAULT '[]',
            transcription TEXT DEFAULT '[]',
            UNIQUE(podcast_id, guid)
        );

        CREATE TABLE IF NOT EXISTS clipping_reports (
            id TEXT PRIMARY KEY,
            created_at DATETIME,
            episode_id TEXT NOT NULL REFERENCES podcast_episodes(id) ON DELETE CASCADE,
            transcription_model_id TEXT REFERENCES ai_models(id),
            analysis_model_id TEXT REFERENCES ai_models(id),
            queued_at DATETIME,
            downloaded_at DATETIME,
            transcribed_at DATETIME,
            analysed_at DATETIME,
            edited_at DATETIME,
            logs TEXT DEFAULT '',
            exceptions TEXT DEFAULT '[]',
            transcription_report TEXT,
            analysis_report TEXT,
            celery_task_id TEXT DEFAULT ''
        );
    """)


def _migrate_ai_models(old_conn, new_conn) -> int:
    rows = old_conn.execute("SELECT * FROM core_aimodel").fetchall()
    count = 0
    for row in rows:
        new_conn.execute(
            """INSERT INTO ai_models (id, created_at, updated_at, name, provider, host,
               is_preset, input_price, output_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(row["id"]),
                row["created_at"],
                row["updated_at"],
                row["name"],
                row["provider"],
                row["host"] or "",
                1 if row["is_preset"] else 0,
                float(row["input_price"] or 0),
                float(row["output_price"] or 0),
            ),
        )
        count += 1
    return count


def _migrate_config(old_conn, new_conn):
    rows = old_conn.execute("SELECT * FROM core_config").fetchall()
    if not rows:
        new_conn.execute("INSERT INTO config (id) VALUES ('config')")
        return

    row = rows[0]
    # Map old FK IDs to new string IDs
    trans_id = str(row["transcription_model_id"]) if row["transcription_model_id"] else None
    analysis_id = str(row["analysis_model_id"]) if row["analysis_model_id"] else None

    new_conn.execute(
        """INSERT INTO config (id, transcription_model_id, analysis_model_id, gemini_api_key)
           VALUES ('config', ?, ?, ?)""",
        (trans_id, analysis_id, row["gemini_api_key"] or ""),
    )


def _migrate_podcast_shows(old_conn, new_conn) -> int:
    rows = old_conn.execute("SELECT * FROM core_podcastshow").fetchall()
    count = 0
    for row in rows:
        new_conn.execute(
            """INSERT INTO podcast_shows (id, created_at, updated_at, title, description,
               itunes_id, source_rss_url, path_directory, has_ads, initial_sync_completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(row["id"]),
                row["created_at"],
                row["updated_at"],
                row["title"],
                row["description"] or "",
                row["itunes_id"],
                row["source_rss_url"],
                row["path_directory"],
                1 if row["has_ads"] else 0,
                1 if row["initial_sync_completed"] else 0,
            ),
        )
        count += 1
    return count


def _migrate_podcast_episodes(old_conn, new_conn) -> int:
    rows = old_conn.execute("SELECT * FROM core_podcastepisode").fetchall()
    count = 0
    for row in rows:
        ads = row["ads"] if row["ads"] else "[]"
        transcription = row["transcription"] if row["transcription"] else "[]"

        # Ensure JSON fields are valid
        try:
            json.loads(ads)
        except (json.JSONDecodeError, TypeError):
            ads = "[]"
        try:
            json.loads(transcription)
        except (json.JSONDecodeError, TypeError):
            transcription = "[]"

        new_conn.execute(
            """INSERT INTO podcast_episodes (id, created_at, updated_at, podcast_id, guid,
               title, published_at, description, duration, source_audio_url, ads, transcription)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(row["id"]),
                row["created_at"],
                row["updated_at"],
                str(row["podcast_id"]),
                row["guid"],
                row["title"],
                row["published_at"],
                row["description"] or "",
                row["duration"],
                row["source_audio_url"] or "",
                ads,
                transcription,
            ),
        )
        count += 1
    return count


def _migrate_clipping_reports(old_conn, new_conn) -> int:
    rows = old_conn.execute("SELECT * FROM core_clippingreport").fetchall()
    count = 0
    for row in rows:
        exceptions = row["exceptions"] if row["exceptions"] else "[]"
        transcription_report = row.get("transcription") if "transcription" in row.keys() else None
        analysis_report = row.get("analysis") if "analysis" in row.keys() else None

        new_conn.execute(
            """INSERT INTO clipping_reports (id, created_at, episode_id,
               transcription_model_id, analysis_model_id, queued_at,
               downloaded_at, transcribed_at, analysed_at, edited_at,
               logs, exceptions, transcription_report, analysis_report, celery_task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')""",
            (
                str(row["id"]),
                row["created_at"],
                str(row["episode_id"]),
                str(row["transcription_model_id"]) if row["transcription_model_id"] else None,
                str(row["analysis_model_id"]) if row["analysis_model_id"] else None,
                row["queued_at"],
                row["downloaded_at"],
                row["transcribed_at"],
                row["analysed_at"],
                row["edited_at"],
                row["logs"] or "",
                exceptions,
                transcription_report,
                analysis_report,
            ),
        )
        count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Clipcast from Django to FastAPI")
    parser.add_argument("--old-db", required=True, help="Path to old Django SQLite database")
    parser.add_argument("--new-db", required=True, help="Path for new database")
    parser.add_argument("--podcasts-dir", help="Path to podcasts directory (for file manifest)")
    args = parser.parse_args()

    migrate(args.old_db, args.new_db, args.podcasts_dir)
