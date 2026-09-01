"""Add request-location/user-input nodes and response storage.

Revision ID: 0006_user_input_flow
Revises: 0005_location_node_enum
"""
from alembic import op
import sqlalchemy as sa

revision="0006_user_input_flow"
down_revision="0005_location_node_enum"
branch_labels=None
depends_on=None

NEW_ENUM="ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','LOCATION','REQUEST_LOCATION','QUESTION','USER_INPUT_FLOW','INTERACTIVE','BUTTON','COMMERCE','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"
OLD_ENUM="ENUM('TRIGGER','SEND_MESSAGE','IMAGE','VIDEO','AUDIO','FILE','LOCATION','QUESTION','INTERACTIVE','BUTTON','COMMERCE','TEMPLATE','ADD_TAG','REMOVE_TAG','SET_FIELD','ASSIGN_USER','SET_STATUS','CONDITION','DELAY','HTTP_REQUEST')"

def upgrade():
    bind=op.get_bind();insp=sa.inspect(bind)
    if insp.has_table('flow_nodes'):
        row=bind.execute(sa.text("SHOW COLUMNS FROM flow_nodes LIKE 'node_type'")).mappings().first()
        if row and ('REQUEST_LOCATION' not in str(row.get('Type','')).upper() or 'USER_INPUT_FLOW' not in str(row.get('Type','')).upper()):op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {NEW_ENUM} NOT NULL"))
    if not insp.has_table('user_input_submissions'):
        op.create_table('user_input_submissions',sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('workspace_id',sa.BigInteger(),sa.ForeignKey('workspaces.id',ondelete='CASCADE'),nullable=False),sa.Column('flow_id',sa.BigInteger(),sa.ForeignKey('flows.id',ondelete='CASCADE'),nullable=False),sa.Column('campaign_node_id',sa.BigInteger(),sa.ForeignKey('flow_nodes.id',ondelete='CASCADE'),nullable=False),sa.Column('channel',sa.String(20),nullable=False),sa.Column('conversation_id',sa.BigInteger(),nullable=False),sa.Column('contact_id',sa.BigInteger(),nullable=False),sa.Column('status',sa.String(20),nullable=False,server_default='active'),sa.Column('webhook_url',sa.Text(),nullable=True),sa.Column('started_at',sa.DateTime(),nullable=False),sa.Column('completed_at',sa.DateTime(),nullable=True))
        op.create_index('ix_user_input_flow_channel_started','user_input_submissions',['flow_id','channel','started_at']);op.create_index('ix_user_input_submissions_workspace_id','user_input_submissions',['workspace_id']);op.create_index('ix_user_input_submissions_conversation_id','user_input_submissions',['conversation_id'])
    if not insp.has_table('user_input_answers'):
        op.create_table('user_input_answers',sa.Column('id',sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column('submission_id',sa.BigInteger(),sa.ForeignKey('user_input_submissions.id',ondelete='CASCADE'),nullable=False),sa.Column('question_node_id',sa.BigInteger(),sa.ForeignKey('flow_nodes.id',ondelete='CASCADE'),nullable=False),sa.Column('answer_key',sa.String(120),nullable=False),sa.Column('question_text',sa.Text(),nullable=True),sa.Column('value_text',sa.Text(),nullable=True),sa.Column('created_at',sa.DateTime(),nullable=False));op.create_index('ix_user_input_answers_submission','user_input_answers',['submission_id','id'])

def downgrade():
    bind=op.get_bind();insp=sa.inspect(bind)
    if insp.has_table('user_input_answers'):op.drop_table('user_input_answers')
    if insp.has_table('user_input_submissions'):op.drop_table('user_input_submissions')
    if insp.has_table('flow_nodes'):
        used=bind.execute(sa.text("SELECT COUNT(*) FROM flow_nodes WHERE node_type IN ('REQUEST_LOCATION','USER_INPUT_FLOW')")).scalar_one()
        if used:raise RuntimeError('Cannot downgrade while request-location/user-input nodes exist')
        op.execute(sa.text(f"ALTER TABLE flow_nodes MODIFY COLUMN node_type {OLD_ENUM} NOT NULL"))