"""Guard: an empty SQLite stepped through `alembic upgrade head` must produce
a schema that matches `SQLModel.metadata` exactly. Catches model changes that
merge without a paired migration — the bug pattern that bit PRs #16 / #18 /
#19 and was patched by #23."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.command import upgrade
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401 — populate SQLModel.metadata

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def test_migrations_match_models(tmp_path):
    db_path = tmp_path / "schema_check.db"
    url = f"sqlite:///{db_path}"

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    upgrade(cfg, "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)

    assert diff == [], (
        "Schema drift between models and migrations — generate the missing "
        f"alembic revision. Diff: {diff!r}"
    )
