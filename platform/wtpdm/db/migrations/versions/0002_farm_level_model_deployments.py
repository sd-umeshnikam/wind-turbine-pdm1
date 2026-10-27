"""farm-level model deployments

The health model bundle covers every component of a farm, so a deployment row is not
always tied to one component.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("model_deployment", "component_code", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM model_deployment WHERE component_code IS NULL")
    op.alter_column("model_deployment", "component_code", existing_type=sa.String(length=32), nullable=False)
