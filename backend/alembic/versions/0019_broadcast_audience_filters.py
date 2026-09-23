"""Broadcast audience filter rules.

Revision ID: 0019_broadcast_audience_filters
Revises: 0018_media_assets
"""
from alembic import op
import sqlalchemy as sa
revision="0019_broadcast_audience_filters";down_revision="0018_media_assets";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("broadcasts",sa.Column("audience_filter_json",sa.Text(),nullable=True))
def downgrade():op.drop_column("broadcasts","audience_filter_json")
