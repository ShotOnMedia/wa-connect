"""Reusable questionnaire campaigns.

Revision ID: 0010_campaigns
Revises: 0009_media_storage_settings
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_campaigns"
down_revision = "0009_media_storage_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind(); inspector = sa.inspect(bind); tables = set(inspector.get_table_names())
    if "campaigns" not in tables:
        op.create_table("campaigns",
            sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("workspace_id",sa.Integer(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("name",sa.String(150),nullable=False),sa.Column("description",sa.Text(),nullable=True),sa.Column("status",sa.String(20),nullable=False,server_default="draft"),sa.Column("channel_scope",sa.String(20),nullable=False,server_default="both"),sa.Column("created_by_user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),sa.UniqueConstraint("workspace_id","name",name="uq_campaign_workspace_name"))
        op.create_index("ix_campaign_workspace_status","campaigns",["workspace_id","status"])
    tables = set(sa.inspect(bind).get_table_names())
    if "campaign_questions" not in tables:
        op.create_table("campaign_questions",
            sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("campaign_id",sa.BigInteger(),sa.ForeignKey("campaigns.id",ondelete="CASCADE"),nullable=False),sa.Column("sort_order",sa.Integer(),nullable=False),sa.Column("title",sa.String(150),nullable=True),sa.Column("question_text",sa.Text(),nullable=False),sa.Column("answer_key",sa.String(120),nullable=False),sa.Column("reply_type",sa.String(40),nullable=False,server_default="text"),sa.Column("required",sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column("capture_field_id",sa.BigInteger(),sa.ForeignKey("contact_field_definitions.id",ondelete="SET NULL"),nullable=True),sa.Column("config_json",sa.Text(),nullable=True),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),sa.UniqueConstraint("campaign_id","sort_order",name="uq_campaign_question_order"))
        op.create_index("ix_campaign_questions_campaign_order","campaign_questions",["campaign_id","sort_order"])


def downgrade():
    bind=op.get_bind();tables=set(sa.inspect(bind).get_table_names())
    if "campaign_questions" in tables:op.drop_table("campaign_questions")
    if "campaigns" in tables:op.drop_table("campaigns")
