"""Add human takeover controls and conversation events.

Revision ID: 0013_conversation_control
Revises: 0012_default_actions
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_conversation_control"
down_revision = "0012_default_actions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "conversation_controls" not in tables:
        op.create_table(
            "conversation_controls",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("conversation_id", sa.BigInteger(), nullable=False),
            sa.Column("human_control", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("taken_over_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("taken_over_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("channel", "conversation_id", name="uq_conversation_control_channel_conversation"),
        )
        op.create_index("ix_conversation_controls_workspace_id", "conversation_controls", ["workspace_id"])
        op.create_index("ix_conversation_controls_lookup", "conversation_controls", ["channel", "conversation_id"])
        op.create_index("ix_conversation_controls_human_control", "conversation_controls", ["human_control"])
        op.create_index("ix_conversation_controls_taken_over_by_user_id", "conversation_controls", ["taken_over_by_user_id"])
    if "conversation_events" not in tables:
        op.create_table(
            "conversation_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("conversation_id", sa.BigInteger(), nullable=False),
            sa.Column("event_type", sa.String(60), nullable=False),
            sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_name", sa.String(150), nullable=True),
            sa.Column("summary", sa.String(255), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_conversation_events_workspace_id", "conversation_events", ["workspace_id"])
        op.create_index("ix_conversation_events_event_type", "conversation_events", ["event_type"])
        op.create_index("ix_conversation_events_actor_user_id", "conversation_events", ["actor_user_id"])
        op.create_index("ix_conversation_events_timeline", "conversation_events", ["channel", "conversation_id", "created_at"])


def downgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "conversation_events" in tables:
        op.drop_table("conversation_events")
    if "conversation_controls" in tables:
        op.drop_table("conversation_controls")
