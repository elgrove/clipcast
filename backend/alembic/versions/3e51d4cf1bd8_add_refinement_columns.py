"""add refinement columns

Revision ID: 3e51d4cf1bd8
Revises: 3c1649611245
Create Date: 2026-05-30 15:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "3e51d4cf1bd8"
down_revision: str | None = "3c1649611245"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("config") as batch:
        batch.add_column(
            sa.Column(
                "boundary_refinement_model_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch.create_foreign_key(
            "fk_config_boundary_refinement_model_id_ai_models",
            "ai_models",
            ["boundary_refinement_model_id"],
            ["id"],
        )

    with op.batch_alter_table("clipping_reports") as batch:
        batch.add_column(
            sa.Column(
                "refinement_model_id",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("refined_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("refinement_report", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_clipping_reports_refinement_model_id_ai_models",
            "ai_models",
            ["refinement_model_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("clipping_reports") as batch:
        batch.drop_constraint(
            "fk_clipping_reports_refinement_model_id_ai_models", type_="foreignkey"
        )
        batch.drop_column("refinement_report")
        batch.drop_column("refined_at")
        batch.drop_column("refinement_model_id")

    with op.batch_alter_table("config") as batch:
        batch.drop_constraint(
            "fk_config_boundary_refinement_model_id_ai_models", type_="foreignkey"
        )
        batch.drop_column("boundary_refinement_model_id")
