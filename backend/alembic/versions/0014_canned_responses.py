"""Add canned responses.
Revision ID: 0014_canned_responses
Revises: 0013_conversation_control
"""
from alembic import op
import sqlalchemy as sa
revision="0014_canned_responses";down_revision="0013_conversation_control";branch_labels=None;depends_on=None

def upgrade():
    if "canned_responses" in sa.inspect(op.get_bind()).get_table_names(): return
    op.create_table("canned_responses",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("workspace_id",sa.BigInteger(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("title",sa.String(150),nullable=False),sa.Column("shortcut",sa.String(80),nullable=False),
        sa.Column("body",sa.Text(),nullable=False),sa.Column("channel",sa.String(20),nullable=False,server_default="both"),
        sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_by_user_id",sa.BigInteger(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.UniqueConstraint("workspace_id","shortcut",name="uq_canned_response_workspace_shortcut"))
    op.create_index("ix_canned_responses_workspace_id","canned_responses",["workspace_id"])
    op.create_index("ix_canned_responses_workspace_channel","canned_responses",["workspace_id","channel","active"])

def downgrade():
    if "canned_responses" in sa.inspect(op.get_bind()).get_table_names(): op.drop_table("canned_responses")
