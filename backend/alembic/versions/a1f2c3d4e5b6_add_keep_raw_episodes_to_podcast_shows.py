"""add keep_raw_episodes to podcast_shows

Revision ID: a1f2c3d4e5b6
Revises: 3e5dad2f9198
Create Date: 2026-06-18 14:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f2c3d4e5b6"
down_revision: str | None = "3e5dad2f9198"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default false backfills existing rows: per-podcast raw retention is
    # off unless explicitly enabled, preserving the prior global-only behaviour.
    # The model carries no server default, but the drift guard does not compare
    # server defaults, so this is not flagged.
    with op.batch_alter_table("podcast_shows") as batch:
        batch.add_column(
            sa.Column(
                "keep_raw_episodes",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("podcast_shows") as batch:
        batch.drop_column("keep_raw_episodes")
