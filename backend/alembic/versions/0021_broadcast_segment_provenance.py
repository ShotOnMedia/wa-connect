"""Track saved segment provenance on broadcasts.

Revision ID: 0021_broadcast_segment_provenance
Revises: 0020_audience_segments
"""
from alembic import op
import sqlalchemy as sa
revision="0021_broadcast_segment_provenance";down_revision="0020_audience_segments";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("broadcasts",sa.Column("audience_segment_id",sa.BigInteger(),nullable=True))
    op.create_foreign_key("fk_broadcasts_audience_segment","broadcasts","audience_segments",["audience_segment_id"],["id"],ondelete="SET NULL")
    op.create_index("ix_broadcasts_audience_segment","broadcasts",["audience_segment_id"])
def downgrade():
    op.drop_index("ix_broadcasts_audience_segment",table_name="broadcasts")
    op.drop_constraint("fk_broadcasts_audience_segment","broadcasts",type_="foreignkey")
    op.drop_column("broadcasts","audience_segment_id")
