"""Link user input submissions and answers to reusable campaigns.

Revision ID: 0011_campaign_submissions
Revises: 0010_campaigns
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_campaign_submissions"
down_revision = "0010_campaigns"
branch_labels = None
depends_on = None


def _columns(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind=op.get_bind();ins=sa.inspect(bind)
    subcols=_columns(ins,"user_input_submissions")
    if "campaign_id" not in subcols:
        op.add_column("user_input_submissions",sa.Column("campaign_id",sa.BigInteger(),nullable=True))
        op.create_foreign_key("fk_user_input_submissions_campaign_id","user_input_submissions","campaigns",["campaign_id"],["id"],ondelete="SET NULL")
        op.create_index("ix_user_input_submissions_campaign_id","user_input_submissions",["campaign_id"])
    anscols=_columns(sa.inspect(bind),"user_input_answers")
    if "campaign_question_id" not in anscols:
        op.add_column("user_input_answers",sa.Column("campaign_question_id",sa.BigInteger(),nullable=True))
        op.create_foreign_key("fk_user_input_answers_campaign_question_id","user_input_answers","campaign_questions",["campaign_question_id"],["id"],ondelete="SET NULL")
        op.create_index("ix_user_input_answers_campaign_question_id","user_input_answers",["campaign_question_id"])
    # Campaign answers do not correspond to a visual FlowNode.
    with op.batch_alter_table("user_input_answers") as batch:
        batch.alter_column("question_node_id",existing_type=sa.BigInteger(),nullable=True)


def downgrade():
    with op.batch_alter_table("user_input_answers") as batch:
        batch.alter_column("question_node_id",existing_type=sa.BigInteger(),nullable=False)
    ins=sa.inspect(op.get_bind());anscols=_columns(ins,"user_input_answers")
    if "campaign_question_id" in anscols:
        op.drop_index("ix_user_input_answers_campaign_question_id",table_name="user_input_answers")
        op.drop_constraint("fk_user_input_answers_campaign_question_id","user_input_answers",type_="foreignkey")
        op.drop_column("user_input_answers","campaign_question_id")
    subcols=_columns(sa.inspect(op.get_bind()),"user_input_submissions")
    if "campaign_id" in subcols:
        op.drop_index("ix_user_input_submissions_campaign_id",table_name="user_input_submissions")
        op.drop_constraint("fk_user_input_submissions_campaign_id","user_input_submissions",type_="foreignkey")
        op.drop_column("user_input_submissions","campaign_id")
