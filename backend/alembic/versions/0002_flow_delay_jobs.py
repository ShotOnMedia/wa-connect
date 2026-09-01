"""Add durable flow delay jobs.

Revision ID: 0002_flow_delay_jobs
Revises: 0001_commerce_node_enum
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_flow_delay_jobs"
down_revision = "0001_commerce_node_enum"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "flow_delay_jobs" in inspector.get_table_names():
        return
    op.create_table(
        "flow_delay_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("flow_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("delay_node_id", sa.BigInteger(), nullable=False),
        sa.Column("resume_node_id", sa.BigInteger(), nullable=True),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delay_node_id"], ["flow_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_node_id"], ["flow_nodes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_flow_delay_jobs_due", "flow_delay_jobs", ["status", "run_at"])
    op.create_index("ix_flow_delay_jobs_flow", "flow_delay_jobs", ["flow_id"])


def downgrade():
    op.drop_table("flow_delay_jobs")
