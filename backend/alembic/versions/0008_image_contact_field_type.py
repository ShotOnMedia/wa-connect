"""add image contact field type

Revision ID: 0008_image_contact_field_type
Revises: 0007_developer_api
"""
from alembic import op

revision = "0008_image_contact_field_type"
down_revision = "0007_developer_api"
branch_labels = None
depends_on = None


def upgrade():
    # SQLAlchemy stores ContactFieldType enum member names in the database.
    op.execute("ALTER TABLE contact_field_definitions MODIFY field_type ENUM('TEXT','TEXTAREA','EMAIL','NUMBER','DATE','SELECT','CHECKBOX','IMAGE') NOT NULL")


def downgrade():
    # Downgrade is only safe when no image definitions remain.
    op.execute("ALTER TABLE contact_field_definitions MODIFY field_type ENUM('TEXT','TEXTAREA','EMAIL','NUMBER','DATE','SELECT','CHECKBOX') NOT NULL")
