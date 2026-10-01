"""campaign templates

Revision ID: 0026_campaign_templates
Revises: 0025_campaign_runtime
"""
from alembic import op
import sqlalchemy as sa

revision="0026_campaign_templates"
down_revision="0025_campaign_runtime"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table(
        "messaging_campaign_templates",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("channel",sa.String(20),nullable=False),
        sa.Column("name",sa.String(150),nullable=False),
        sa.Column("description",sa.Text(),nullable=True),
        sa.Column("steps_json",sa.Text(),nullable=False),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.Column("updated_at",sa.DateTime(),nullable=False),
    )
    op.create_index("ix_msg_campaign_template_workspace_id","messaging_campaign_templates",["workspace_id"])
    op.create_index("ix_msg_campaign_template_channel","messaging_campaign_templates",["channel"])
    op.create_index("ix_msg_campaign_template_workspace_channel","messaging_campaign_templates",["workspace_id","channel"])

def downgrade():
    op.drop_table("messaging_campaign_templates")
