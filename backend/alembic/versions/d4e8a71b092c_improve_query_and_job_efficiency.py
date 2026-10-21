"""Add query indexes and active job claims."""

from alembic import op
import sqlalchemy as sa

revision = "d4e8a71b092c"
down_revision = "395988822d5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clipping_reports", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column(
        "clipping_reports",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "clipping_reports",
        sa.Column("download_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_episode_podcast_published", "podcast_episodes", ["podcast_id", "published_at"]
    )
    op.create_index("ix_episode_podcast_guid", "podcast_episodes", ["podcast_id", "guid"])
    op.create_index("ix_report_episode_queued", "clipping_reports", ["episode_id", "queued_at"])
    op.create_index("ix_report_queued", "clipping_reports", ["queued_at"])
    # Preserve one recent claim per episode while old worker tasks finish.
    op.execute(
        sa.text("""
        UPDATE clipping_reports SET active = 1, lease_until = datetime('now', '+24 hours')
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY episode_id ORDER BY queued_at DESC, id DESC) AS position
                FROM clipping_reports WHERE edited_at IS NULL AND exceptions = '[]'
                AND queued_at > datetime('now', '-4 hours')
            ) WHERE position = 1
        )
    """)
    )
    op.create_index(
        "uq_report_active_episode",
        "clipping_reports",
        ["episode_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )


def downgrade():
    for name in ("uq_report_active_episode", "ix_report_queued", "ix_report_episode_queued"):
        op.drop_index(name, table_name="clipping_reports")
    for name in ("ix_episode_podcast_guid", "ix_episode_podcast_published"):
        op.drop_index(name, table_name="podcast_episodes")
    op.drop_column("clipping_reports", "download_only")
    op.drop_column("clipping_reports", "active")
    op.drop_column("clipping_reports", "lease_until")
