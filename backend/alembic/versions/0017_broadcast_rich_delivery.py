"""Broadcast rich content and delivery pacing.

Revision ID: 0017_broadcast_rich_delivery
Revises: 0016_broadcasts
"""
from alembic import op
import sqlalchemy as sa
revision="0017_broadcast_rich_delivery";down_revision="0016_broadcasts";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("broadcasts",sa.Column("parse_mode",sa.String(20),nullable=False,server_default="HTML"))
    op.add_column("broadcasts",sa.Column("media_url",sa.Text(),nullable=True))
    op.add_column("broadcasts",sa.Column("media_type",sa.String(20),nullable=True))
    op.add_column("broadcasts",sa.Column("stagger_seconds",sa.Float(),nullable=False,server_default="0.05"))
    op.add_column("broadcasts",sa.Column("last_sent_at",sa.DateTime(),nullable=True))
def downgrade():
    for c in ["last_sent_at","stagger_seconds","media_type","media_url","parse_mode"]:op.drop_column("broadcasts",c)
