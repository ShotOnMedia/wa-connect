"""Add persistent flow run and event tracking.

Revision ID: 0003_flow_run_tracking
Revises: 0002_flow_delay_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_flow_run_tracking"
down_revision = "0002_flow_delay_jobs"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name):
    inspector = sa.inspect(op.get_bind())
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade():
    tables = _tables()
    if "flow_runs" not in tables:
        op.create_table(
            "flow_runs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("flow_id", sa.BigInteger(), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("conversation_id", sa.BigInteger(), nullable=False),
            sa.Column("contact_id", sa.BigInteger(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="running"),
            sa.Column("current_node_id", sa.BigInteger(), sa.ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("error_type", sa.String(160), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    indexes = _indexes("flow_runs")
    if "ix_flow_runs_flow_started" not in indexes:
        op.create_index("ix_flow_runs_flow_started", "flow_runs", ["flow_id", "started_at"])
    if "ix_flow_runs_channel_conversation" not in indexes:
        op.create_index("ix_flow_runs_channel_conversation", "flow_runs", ["channel", "conversation_id", "started_at"])
    if "ix_flow_runs_status_updated" not in indexes:
        op.create_index("ix_flow_runs_status_updated", "flow_runs", ["status", "updated_at"])

    tables = _tables()
    if "flow_run_events" not in tables:
        op.create_table(
            "flow_run_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("flow_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("node_type", sa.String(50), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    indexes = _indexes("flow_run_events")
    if "ix_flow_run_events_run_created" not in indexes:
        op.create_index("ix_flow_run_events_run_created", "flow_run_events", ["run_id", "created_at"])


def downgrade():
    tables = _tables()
    if "flow_run_events" in tables:
        op.drop_table("flow_run_events")
    if "flow_runs" in tables:
        op.drop_table("flow_runs")
