"""add scan_acast_ads config column

Revision ID: 3e5dad2f9198
Revises: 7b7b36cd579a
Create Date: 2026-06-10 22:54:32.928878

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3e5dad2f9198"
down_revision: str | None = "7b7b36cd579a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default true backfills the existing singleton config row so the
    # Acast AI scan is on by default after upgrade; the model carries no server
    # default, but the drift guard does not compare server defaults, so this is
    # not flagged.
    with op.batch_alter_table("config") as batch:
        batch.add_column(
            sa.Column(
                "scan_acast_ads",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("config") as batch:
        batch.drop_column("scan_acast_ads")
