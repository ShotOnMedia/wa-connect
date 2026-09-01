"""Add LOCATION flow-node support.

Revision ID: 0005_location_node_enum
Revises: 0004_http_apis
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_location_node_enum"
down_revision = "0004_http_apis"
branch_labels = None
depends_on = None

WITH_LOCATION = "ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','LOCATION','QUESTION','INTERACTIVE','BUTTON','COMMERCE','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"
WITHOUT_LOCATION = "ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','QUESTION','INTERACTIVE','BUTTON','COMMERCE','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"


def _exists(bind):
    return sa.inspect(bind).has_table("flow_nodes")


def _has_location(bind):
    row=bind.execute(sa.text("SHOW COLUMNS FROM flow_nodes LIKE 'node_type'")).mappings().first()
    return bool(row and "LOCATION" in str(row.get("Type","")).upper())


def upgrade():
    bind=op.get_bind()
    if _exists(bind) and not _has_location(bind):
        op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {WITH_LOCATION} NOT NULL"))


def downgrade():
    bind=op.get_bind()
    if not _exists(bind) or not _has_location(bind):return
    used=bind.execute(sa.text("SELECT COUNT(*) FROM flow_nodes WHERE node_type='LOCATION'")).scalar_one()
    if used:raise RuntimeError("Cannot downgrade: flow_nodes contains LOCATION nodes")
    op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {WITHOUT_LOCATION} NOT NULL"))