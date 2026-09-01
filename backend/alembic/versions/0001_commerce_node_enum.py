"""Baseline existing WA Connect schema and ensure Commerce flow-node support.

Revision ID: 0001_commerce_node_enum
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_commerce_node_enum"
down_revision = None
branch_labels = None
depends_on = None

FLOW_NODE_ENUM_WITH_COMMERCE = "ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','QUESTION','INTERACTIVE','BUTTON','COMMERCE','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"
FLOW_NODE_ENUM_WITHOUT_COMMERCE = "ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','QUESTION','INTERACTIVE','BUTTON','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"


def _flow_nodes_exists(bind) -> bool:
    return sa.inspect(bind).has_table("flow_nodes")


def _node_type_has_commerce(bind) -> bool:
    row = bind.execute(sa.text("SHOW COLUMNS FROM flow_nodes LIKE 'node_type'")).mappings().first()
    return bool(row and "COMMERCE" in str(row.get("Type", "")).upper())


def upgrade() -> None:
    bind = op.get_bind()
    # Existing v0.2 installations already have the tables from create_all().
    # Fresh installations may not yet have flow_nodes; current metadata will
    # create it with COMMERCE during application bootstrap.
    if _flow_nodes_exists(bind) and not _node_type_has_commerce(bind):
        op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {FLOW_NODE_ENUM_WITH_COMMERCE} NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if not _flow_nodes_exists(bind) or not _node_type_has_commerce(bind):
        return
    used = bind.execute(sa.text("SELECT COUNT(*) FROM flow_nodes WHERE node_type='COMMERCE'")).scalar_one()
    if used:
        raise RuntimeError("Cannot downgrade: flow_nodes contains COMMERCE nodes")
    op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {FLOW_NODE_ENUM_WITHOUT_COMMERCE} NOT NULL"))
