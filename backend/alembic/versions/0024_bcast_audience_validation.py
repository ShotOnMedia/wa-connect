"""Broadcast audience validation snapshot.

Revision ID: 0024_bcast_audience_validation
Revises: 0023_wa_template_bcasts
"""
from alembic import op
import sqlalchemy as sa
revision="0024_bcast_audience_validation";down_revision="0023_wa_template_bcasts";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("broadcasts",sa.Column("audience_evaluated_count",sa.Integer(),nullable=False,server_default="0"))
    op.add_column("broadcasts",sa.Column("audience_validation_json",sa.Text(),nullable=True))
def downgrade():
    op.drop_column("broadcasts","audience_validation_json");op.drop_column("broadcasts","audience_evaluated_count")
