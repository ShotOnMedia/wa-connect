import re
from sqlalchemy import select
from app.models import ContactFieldDefinition,ContactFieldValue,Conversation
from app.services.user_input_values import latest_input_answer
from app.telegram_models import TelegramContactFieldValue,TelegramConversation
VARIABLE_RE=re.compile(r'%([A-Za-z0-9_.-]+)%');INPUT_PREFIX='input.'
def _keys(text):value=str(text or '');return value,set(VARIABLE_RE.findall(value))
def _replace(value,values):return VARIABLE_RE.sub(lambda m:str(values.get(m.group(1)) or ''),value)
def _input_values(db,cid,channel,keys):return {key:latest_input_answer(db,cid,channel,key[len(INPUT_PREFIX):]) for key in keys if key.startswith(INPUT_PREFIX)}
def render_whatsapp(db,conversation,text):
    value,keys=_keys(text)
    if not keys:return value
    field_keys={key for key in keys if not key.startswith(INPUT_PREFIX)};values=_input_values(db,conversation.id,'whatsapp',keys)
    if field_keys:
        rows=db.execute(select(ContactFieldDefinition.key,ContactFieldValue.value_text).outerjoin(ContactFieldValue,(ContactFieldValue.field_id==ContactFieldDefinition.id)&(ContactFieldValue.contact_id==conversation.contact_id)).where(ContactFieldDefinition.workspace_id==conversation.workspace_id,ContactFieldDefinition.key.in_(field_keys))).all();values.update({str(k):v for k,v in rows})
    return _replace(value,values)
def render_telegram(db,conversation,text):
    value,keys=_keys(text)
    if not keys:return value
    field_keys={key for key in keys if not key.startswith(INPUT_PREFIX)};values=_input_values(db,conversation.id,'telegram',keys)
    if field_keys:
        rows=db.execute(select(ContactFieldDefinition.key,TelegramContactFieldValue.value_text).join(TelegramContactFieldValue,TelegramContactFieldValue.field_id==ContactFieldDefinition.id).where(TelegramContactFieldValue.contact_id==conversation.contact_id,ContactFieldDefinition.key.in_(field_keys))).all();values.update({str(k):v for k,v in rows})
    return _replace(value,values)
