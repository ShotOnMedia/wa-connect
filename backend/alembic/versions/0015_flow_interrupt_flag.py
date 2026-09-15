"""Persist interrupt-active-flow on flows.

Revision ID: 0015_flow_interrupt_flag
Revises: 0014_canned_responses
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_flow_interrupt_flag"
down_revision = "0014_canned_responses"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("flows", sa.Column("interrupt_active_flow", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Preserve existing opt-ins from the legacy Trigger-node JSON. MariaDB's
    # JSON_EXTRACT works on the TEXT config_json column and returns JSON true.
    op.execute(sa.text("""
        UPDATE flows f
        JOIN flow_nodes n ON n.flow_id = f.id AND n.node_type = 'TRIGGER'
        SET f.interrupt_active_flow = 1
        WHERE JSON_VALID(n.config_json)
          AND JSON_EXTRACT(n.config_json, '$.interrupt_active_flow') = true
    """))


def downgrade():
    op.drop_column("flows", "interrupt_active_flow")
