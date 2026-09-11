import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin, require_user
from app.models import Contact, ContactFieldDefinition, ContactFieldType, ContactFieldValue, Conversation, User, UserRole, Workspace
from app.schemas import ContactCustomFieldOut, ContactFieldDefinitionCreate, ContactFieldDefinitionOut, ContactFieldDefinitionUpdate, ContactFieldValueUpdate
from app.services.system_fields import SYSTEM_FIELD_KEYS, ensure_system_fields, ensure_system_fields_all_workspaces, sync_telegram_system_fields, sync_whatsapp_system_fields
from app.telegram_models import TelegramContact, TelegramContactFieldValue, TelegramConversation

router = APIRouter(tags=["contact-fields"])


def _raw_meta(raw:str|None):
    if not raw:return None
    try:return json.loads(raw)
    except (TypeError,ValueError):return None

def _options(raw: str | None) -> list[str]:
    value=_raw_meta(raw)
    if isinstance(value,list):return value
    if isinstance(value,dict) and isinstance(value.get("options"),list):return value["options"]
    return []

def _protected(raw:str|None)->bool:
    value=_raw_meta(raw);return bool(value.get("protected")) if isinstance(value,dict) else False

def _encode_meta(options:list[str],protected:bool)->str:
    return json.dumps({"options":options,"protected":True}) if protected else json.dumps(options)

def _definition_out(field:ContactFieldDefinition)->ContactFieldDefinitionOut:
    return ContactFieldDefinitionOut(id=field.id,key=field.key,label=field.label,field_type=field.field_type,options=_options(field.options_json),required=field.required,active=field.active,protected=_protected(field.options_json),sort_order=field.sort_order)

def _field_payload(field,value,user=None):
    protected=_protected(field.options_json);writable=not (protected and user is not None and (user.role==UserRole.AGENT or getattr(user.role,'value',user.role)=='agent'))
    return {**_definition_out(field).model_dump(mode="json"),"value":value,"system":field.key in SYSTEM_FIELD_KEYS,"variable":f"%{field.key}%","writable":writable}

def _is_agent(user):return user.role==UserRole.AGENT or getattr(user.role,'value',user.role)=='agent'
def _assert_wa_contact_access(db,contact_id,user):
    if _is_agent(user) and not db.scalar(select(Conversation.id).where(Conversation.contact_id==contact_id,Conversation.assigned_user_id==user.id).limit(1)):raise HTTPException(status_code=403,detail="This contact is not assigned to you")
def _assert_tg_contact_access(db,contact_id,user):
    if _is_agent(user) and not db.scalar(select(TelegramConversation.id).where(TelegramConversation.contact_id==contact_id,TelegramConversation.assigned_user_id==user.id).limit(1)):raise HTTPException(status_code=403,detail="This contact is not assigned to you")

def _workspace_ids(db:Session)->list[int]:
    ids=list(db.scalars(select(Workspace.id).order_by(Workspace.id.asc())).all())
    if not ids: raise HTTPException(status_code=400,detail="No workspace is available yet")
    return ids

def _workspace_id(db:Session)->int:return _workspace_ids(db)[0]

def _clean_options(field_type:ContactFieldType,options:list[str])->list[str]:
    if field_type!=ContactFieldType.SELECT:return []
    cleaned=[]
    for option in options:
        option=str(option).strip()
        if option and option not in cleaned:cleaned.append(option)
    if not cleaned:raise HTTPException(status_code=422,detail="Select fields require at least one option")
    return cleaned

def _platform_rows(db:Session):
    ensure_system_fields_all_workspaces(db)
    for contact in db.scalars(select(Contact)).all(): sync_whatsapp_system_fields(db,contact,contact.name)
    for contact in db.scalars(select(TelegramContact)).all(): sync_telegram_system_fields(db,contact)
    db.commit();workspace_id=_workspace_id(db)
    return db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id==workspace_id).order_by(ContactFieldDefinition.sort_order.asc(),ContactFieldDefinition.label.asc())).all()

@router.get("/contact-fields",response_model=list[ContactFieldDefinitionOut])
def list_contact_fields(db:Session=Depends(get_db)):
    return [_definition_out(field) for field in _platform_rows(db)]

@router.get("/contact-fields/platform")
def list_platform_contact_fields(db:Session=Depends(get_db),_:User=Depends(require_admin)):
    return [{**_definition_out(field).model_dump(mode="json"),"system":field.key in SYSTEM_FIELD_KEYS,"variable":f"%{field.key}%"} for field in _platform_rows(db)]

@router.post("/contact-fields",response_model=ContactFieldDefinitionOut,status_code=status.HTTP_201_CREATED)
def create_contact_field(payload:ContactFieldDefinitionCreate,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    key=payload.key.strip().lower()
    if key in SYSTEM_FIELD_KEYS:raise HTTPException(status_code=409,detail="That key is reserved for a system field")
    created=None
    for workspace_id in _workspace_ids(db):
        if db.scalar(select(ContactFieldDefinition.id).where(ContactFieldDefinition.workspace_id==workspace_id,ContactFieldDefinition.key==key)):raise HTTPException(status_code=409,detail="A contact field with this key already exists")
    options=_clean_options(payload.field_type,payload.options);metadata=_encode_meta(options,payload.protected)
    for workspace_id in _workspace_ids(db):
        field=ContactFieldDefinition(workspace_id=workspace_id,key=key,label=payload.label.strip(),field_type=payload.field_type,options_json=metadata,required=payload.required,active=payload.active,sort_order=payload.sort_order);db.add(field);db.flush()
        if created is None:created=field
    db.commit();db.refresh(created);return _definition_out(created)

@router.patch("/contact-fields/{field_id}",response_model=ContactFieldDefinitionOut)
def update_contact_field(field_id:int,payload:ContactFieldDefinitionUpdate,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    field=db.get(ContactFieldDefinition,field_id)
    if not field:raise HTTPException(status_code=404,detail="Contact field not found")
    data=payload.model_dump(exclude_unset=True)
    if field.key in SYSTEM_FIELD_KEYS:
        forbidden={"field_type","options","required","active","protected"}.intersection(data)
        if forbidden:raise HTTPException(status_code=422,detail="System field type, options, required state, active state and protection are maintained automatically")
    siblings=db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.key==field.key)).all();next_type=data.get("field_type",field.field_type)
    current_options=_options(field.options_json);current_protected=_protected(field.options_json)
    next_options=_clean_options(next_type,data.get("options",current_options)) if ("options" in data or "field_type" in data) else current_options
    next_protected=bool(data.get("protected",current_protected))
    for sibling in siblings:
        if "label" in data:sibling.label=data["label"].strip()
        if "field_type" in data:sibling.field_type=data["field_type"]
        if "options" in data or "field_type" in data or "protected" in data:sibling.options_json=_encode_meta(next_options,next_protected)
        for attr in ("required","active","sort_order"):
            if attr in data:setattr(sibling,attr,data[attr])
        sibling.updated_at=datetime.utcnow()
    db.commit();db.refresh(field);return _definition_out(field)

@router.delete("/contact-fields/{field_id}",status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_field(field_id:int,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    field=db.get(ContactFieldDefinition,field_id)
    if not field:raise HTTPException(status_code=404,detail="Contact field not found")
    if field.key in SYSTEM_FIELD_KEYS:raise HTTPException(status_code=422,detail="System fields cannot be deleted")
    for sibling in db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.key==field.key)).all():db.delete(sibling)
    db.commit()

@router.get("/contacts/{contact_id}/custom-fields",response_model=list[ContactCustomFieldOut])
def get_contact_custom_fields(contact_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    contact=db.get(Contact,contact_id)
    if not contact:raise HTTPException(status_code=404,detail="Contact not found")
    _assert_wa_contact_access(db,contact_id,user)
    ensure_system_fields(db,contact.workspace_id);sync_whatsapp_system_fields(db,contact,contact.name);db.commit()
    rows=db.execute(select(ContactFieldDefinition,ContactFieldValue.value_text).outerjoin(ContactFieldValue,(ContactFieldValue.field_id==ContactFieldDefinition.id)&(ContactFieldValue.contact_id==contact_id)).where(ContactFieldDefinition.workspace_id==contact.workspace_id,ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order.asc(),ContactFieldDefinition.label.asc())).all()
    return [ContactCustomFieldOut(**_definition_out(field).model_dump(),value=value,writable=not (_protected(field.options_json) and _is_agent(user))) for field,value in rows]

@router.put("/contacts/{contact_id}/custom-fields/{field_id}",response_model=ContactCustomFieldOut)
def set_contact_custom_field(contact_id:int,field_id:int,payload:ContactFieldValueUpdate,db:Session=Depends(get_db),user:User=Depends(require_user)):
    contact=db.get(Contact,contact_id);field=db.get(ContactFieldDefinition,field_id)
    if not contact or not field or field.workspace_id!=contact.workspace_id or not field.active:raise HTTPException(status_code=404,detail="Contact or custom field not found")
    _assert_wa_contact_access(db,contact_id,user)
    if _protected(field.options_json) and _is_agent(user):raise HTTPException(status_code=403,detail=f"{field.label} is protected and cannot be changed by agents")
    value=payload.value
    if isinstance(value,bool):value_text="true" if value else "false"
    elif value is None:value_text=None
    else:value_text=str(value).strip()
    if field.required and not value_text:raise HTTPException(status_code=422,detail=f"{field.label} is required")
    if field.field_type==ContactFieldType.SELECT and value_text and value_text not in _options(field.options_json):raise HTTPException(status_code=422,detail="Value is not one of the configured options")
    if field.field_type==ContactFieldType.CHECKBOX and value_text not in {None,"true","false"}:raise HTTPException(status_code=422,detail="Checkbox value must be true or false")
    existing=db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id==contact_id,ContactFieldValue.field_id==field_id))
    if not value_text and not field.required:
        if existing:db.delete(existing)
    elif existing:existing.value_text=value_text;existing.updated_at=datetime.utcnow()
    else:db.add(ContactFieldValue(contact_id=contact_id,field_id=field_id,value_text=value_text))
    contact.updated_at=datetime.utcnow();db.commit();return ContactCustomFieldOut(**_definition_out(field).model_dump(),value=value_text,writable=not (_protected(field.options_json) and _is_agent(user)))

@router.get("/telegram/contacts/{contact_id}/custom-fields")
def get_telegram_contact_custom_fields(contact_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    contact=db.get(TelegramContact,contact_id)
    if not contact:raise HTTPException(status_code=404,detail="Telegram contact not found")
    _assert_tg_contact_access(db,contact_id,user)
    ensure_system_fields(db,contact.workspace_id);sync_telegram_system_fields(db,contact);db.commit()
    rows=db.execute(select(ContactFieldDefinition,TelegramContactFieldValue.value_text).outerjoin(TelegramContactFieldValue,(TelegramContactFieldValue.field_id==ContactFieldDefinition.id)&(TelegramContactFieldValue.contact_id==contact_id)).where(ContactFieldDefinition.workspace_id==contact.workspace_id,ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order.asc(),ContactFieldDefinition.label.asc())).all()
    return [_field_payload(field,value,user) for field,value in rows]

@router.put("/telegram/contacts/{contact_id}/custom-fields/{field_id}")
def set_telegram_contact_custom_field(contact_id:int,field_id:int,payload:ContactFieldValueUpdate,db:Session=Depends(get_db),user:User=Depends(require_user)):
    contact=db.get(TelegramContact,contact_id);field=db.get(ContactFieldDefinition,field_id)
    if not contact or not field or field.workspace_id!=contact.workspace_id or not field.active:raise HTTPException(status_code=404,detail="Telegram contact or custom field not found")
    _assert_tg_contact_access(db,contact_id,user)
    if field.key in SYSTEM_FIELD_KEYS:raise HTTPException(status_code=422,detail="System fields are maintained automatically")
    if _protected(field.options_json) and _is_agent(user):raise HTTPException(status_code=403,detail=f"{field.label} is protected and cannot be changed by agents")
    value=payload.value
    if isinstance(value,bool):value_text="true" if value else "false"
    elif value is None:value_text=None
    else:value_text=str(value).strip()
    if field.required and not value_text:raise HTTPException(status_code=422,detail=f"{field.label} is required")
    if field.field_type==ContactFieldType.SELECT and value_text and value_text not in _options(field.options_json):raise HTTPException(status_code=422,detail="Value is not one of the configured options")
    if field.field_type==ContactFieldType.CHECKBOX and value_text not in {None,"true","false"}:raise HTTPException(status_code=422,detail="Checkbox value must be true or false")
    row=db.scalar(select(TelegramContactFieldValue).where(TelegramContactFieldValue.contact_id==contact_id,TelegramContactFieldValue.field_id==field_id))
    if not value_text and not field.required:
        if row:db.delete(row)
    elif row:row.value_text=value_text;row.updated_at=datetime.utcnow()
    else:db.add(TelegramContactFieldValue(contact_id=contact_id,field_id=field_id,value_text=value_text))
    contact.updated_at=datetime.utcnow();db.commit();return _field_payload(field,value_text,user)