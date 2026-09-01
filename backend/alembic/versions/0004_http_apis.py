"""Add reusable HTTP API integrations and call history.

Revision ID: 0004_http_apis
Revises: 0003_flow_run_tracking
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_http_apis"
down_revision = "0003_flow_run_tracking"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "http_apis" not in tables:
        op.create_table(
            "http_apis",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("method", sa.String(10), nullable=False, server_default="GET"),
            sa.Column("endpoint_url", sa.Text(), nullable=False),
            sa.Column("headers_json", sa.Text(), nullable=True),
            sa.Column("query_json", sa.Text(), nullable=True),
            sa.Column("cookies_json", sa.Text(), nullable=True),
            sa.Column("body_type", sa.String(30), nullable=False, server_default="none"),
            sa.Column("body_json", sa.Text(), nullable=True),
            sa.Column("response_mappings_json", sa.Text(), nullable=True),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("total_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_success", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_error", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_called_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_http_apis_name", "http_apis", ["name"])
        op.create_index("ix_http_apis_active", "http_apis", ["active"])
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "http_api_calls" not in tables:
        op.create_table(
            "http_api_calls",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("http_api_id", sa.BigInteger(), sa.ForeignKey("http_apis.id", ondelete="CASCADE"), nullable=False),
            sa.Column("flow_run_id", sa.BigInteger(), sa.ForeignKey("flow_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("response_preview", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_http_api_calls_http_api_id", "http_api_calls", ["http_api_id"])
        op.create_index("ix_http_api_calls_flow_run_id", "http_api_calls", ["flow_run_id"])
        op.create_index("ix_http_api_calls_api_created", "http_api_calls", ["http_api_id", "created_at"])
        op.create_index("ix_http_api_calls_success_created", "http_api_calls", ["success", "created_at"])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "http_api_calls" in tables:
        op.drop_table("http_api_calls")
    if "http_apis" in tables:
        op.drop_table("http_apis")
