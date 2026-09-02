"""developer API keys and request logs

Revision ID: 0007_developer_api
Revises: 0006_user_input_flow
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_developer_api"
down_revision = "0006_user_input_flow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "developer_api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("key_prefix", name="uq_developer_api_key_prefix"),
        sa.UniqueConstraint("token_hash", name="uq_developer_api_token_hash"),
    )
    op.create_index("ix_developer_api_keys_workspace_id", "developer_api_keys", ["workspace_id"])
    op.create_index("ix_developer_api_keys_workspace_active", "developer_api_keys", ["workspace_id", "active"])
    op.create_index("ix_developer_api_keys_prefix", "developer_api_keys", ["key_prefix"])
    op.create_index("ix_developer_api_keys_token_hash", "developer_api_keys", ["token_hash"])

    op.create_table(
        "developer_api_request_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.BigInteger(), sa.ForeignKey("developer_api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("remote_addr", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_developer_api_request_logs_workspace_id", "developer_api_request_logs", ["workspace_id"])
    op.create_index("ix_developer_api_request_logs_api_key_id", "developer_api_request_logs", ["api_key_id"])
    op.create_index("ix_developer_api_request_logs_created_at", "developer_api_request_logs", ["created_at"])
    op.create_index("ix_developer_api_logs_workspace_created", "developer_api_request_logs", ["workspace_id", "created_at"])
    op.create_index("ix_developer_api_logs_key_created", "developer_api_request_logs", ["api_key_id", "created_at"])


def downgrade():
    op.drop_table("developer_api_request_logs")
    op.drop_table("developer_api_keys")
