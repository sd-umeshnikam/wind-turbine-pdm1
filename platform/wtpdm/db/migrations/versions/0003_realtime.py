"""real-time operation: replay progress, alarm flag, alert condition state

- replay_state: position in the turbine's replay timeline, timeline length, loop count,
  the CARE event the current row belongs to and the turbine's operating status code.
- health_score.alarm: the detector's persistent alarm on the turbine-level row.
- alert: whether the triggering condition is still present (return-to-normal does not
  close an alert; an engineer resolves it), and the last data time it was seen.
- Age-based compression is removed: replayed rows keep their anonymised dataset
  timestamps (2014-2029), so "older than 7 days" would compress the very chunks the
  replay is writing into.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HYPERTABLES = ("telemetry", "health_score")


def upgrade() -> None:
    op.add_column("replay_state", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("replay_state", sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("replay_state", sa.Column("cycle", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("replay_state", sa.Column("source_event_id", sa.Integer(), nullable=True))
    op.add_column("replay_state", sa.Column("operating_status", sa.SmallInteger(), nullable=True))
    op.add_column("health_score", sa.Column("alarm", sa.Boolean(), nullable=True))
    op.add_column(
        "alert", sa.Column("condition_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("alert", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alert", sa.Column("last_data_ts", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_retrain_job_status", "retrain_job", ["status"])
    for table in HYPERTABLES:
        op.execute(f"SELECT remove_compression_policy('{table}', if_exists => true)")


def downgrade() -> None:
    for table in HYPERTABLES:
        op.execute(f"SELECT add_compression_policy('{table}', INTERVAL '7 days', if_not_exists => true)")
    op.drop_index("ix_retrain_job_status", table_name="retrain_job")
    for col in ("last_data_ts", "cleared_at", "condition_active"):
        op.drop_column("alert", col)
    op.drop_column("health_score", "alarm")
    for col in ("operating_status", "source_event_id", "cycle", "total_rows", "position"):
        op.drop_column("replay_state", col)
