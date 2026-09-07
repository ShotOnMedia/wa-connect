from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ContactFieldDefinition,ContactFieldValue,ContactTag,ContactTagLink,Conversation
from app.services.service_window import service_window_open
from app.services.user_input_values import latest_input_answer

def compare(actual,expected,operator):
    a=str(actual or '').strip();e=str(expected or '').strip();op=str(operator or 'equals')
    if op in {'equals','open'}:return a.casefold()==e.casefold()
    if op in {'not_equals','closed'}:return a.casefold()!=e.casefold()
    if op=='contains':return e.casefold() in a.casefold()
    if op=='not_contains':return e.casefold() not in a.casefold()
    if op=='starts_with':return a.casefold().startswith(e.casefold())
    if op=='ends_with':return a.casefold().endswith(e.casefold())
    if op=='empty':return not a
    if op=='not_empty':return bool(a)
    return False

def condition_result(db:Session,conversation:Conversation,config:dict)->bool:
    field=str(config.get('field') or 'service_window');operator=str(config.get('operator') or 'open');expected=str(config.get('value') or '').strip()
    if field=='user_input':
        key,_,compare_value=str(config.get('value') or '').partition('\x1f');return compare(latest_input_answer(db,conversation.id,'whatsapp',key),compare_value,operator)
    if field=='service_window':return service_window_open(conversation) if operator in {'open','equals'} else not service_window_open(conversation) if operator in {'closed','not_equals'} else False
    if field=='conversation_status':return compare(conversation.status.value,expected,operator)
    if field=='assigned_user':return compare('' if conversation.assigned_user_id is None else str(conversation.assigned_user_id),expected,operator)
    if field=='tag':
        names=set(db.scalars(select(ContactTag.name).join(ContactTagLink,ContactTagLink.tag_id==ContactTag.id).where(ContactTagLink.contact_id==conversation.contact_id)).all())
        if operator=='empty':return not names
        if operator=='not_empty':return bool(names)
        matched=any(name.casefold()==expected.casefold() for name in names);return not matched if operator in {'not_equals','not_contains'} else matched
    if field=='custom_field':
        key=str(config.get('field_key') or config.get('key') or expected).strip();compare_value=str(config.get('compare_value') if 'compare_value' in config else ('' if key==expected else expected)).strip();row=db.execute(select(ContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==ContactFieldValue.field_id).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldDefinition.key==key)).first();return compare((row[0] if row else '') or '',compare_value,operator)
    return False
