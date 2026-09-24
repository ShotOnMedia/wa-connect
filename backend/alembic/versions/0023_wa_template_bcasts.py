"""WhatsApp template broadcast snapshot.

Revision ID: 0023_wa_template_bcasts
Revises: 0022_broadcast_templates
"""
from alembic import op
import sqlalchemy as sa
revision="0023_wa_template_bcasts";down_revision="0022_broadcast_templates";branch_labels=None;depends_on=None
def upgrade():
    op.add_column("broadcasts",sa.Column("message_mode",sa.String(20),nullable=False,server_default="freeform"))
    op.add_column("broadcasts",sa.Column("provider_template_json",sa.Text(),nullable=True))
    op.add_column("broadcast_recipients",sa.Column("provider_payload_json",sa.Text(),nullable=True))
def downgrade():
    op.drop_column("broadcast_recipients","provider_payload_json");op.drop_column("broadcasts","provider_template_json");op.drop_column("broadcasts","message_mode")
