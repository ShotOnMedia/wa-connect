from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models import ContactFieldType, ConversationStatus, MessageDirection, MessageStatus, UserRole

class ContactOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int; wa_id:str; name:str|None; archived_at:datetime|None=None; blocked_at:datetime|None=None
class ContactTagOut(BaseModel):
    model_config=ConfigDict(from_attributes=True); id:int; name:str
class ContactTagCreate(BaseModel): name:str=Field(min_length=1,max_length=80)
class ContactNoteCreate(BaseModel): body:str=Field(min_length=1,max_length=10000)
class ContactNoteOut(BaseModel):
    id:int; body:str; user_id:int; author_name:str; created_at:datetime; updated_at:datetime
class ContactFieldDefinitionCreate(BaseModel):
    key:str=Field(min_length=1,max_length=80,pattern=r"^[a-z][a-z0-9_]*$"); label:str=Field(min_length=1,max_length=120); field_type:ContactFieldType; options:list[str]=[]; required:bool=False; active:bool=True; sort_order:int=0
class ContactFieldDefinitionUpdate(BaseModel):
    label:str|None=Field(default=None,min_length=1,max_length=120); field_type:ContactFieldType|None=None; options:list[str]|None=None; required:bool|None=None; active:bool|None=None; sort_order:int|None=None
class ContactFieldDefinitionOut(BaseModel):
    id:int; key:str; label:str; field_type:ContactFieldType; options:list[str]=[]; required:bool; active:bool; sort_order:int
class ContactCustomFieldOut(ContactFieldDefinitionOut): value:str|None=None
class ContactFieldValueUpdate(BaseModel): value:str|bool|int|float|None=None
class ContactListOut(ContactOut):
    created_at:datetime; updated_at:datetime; conversation_count:int=0; last_message_at:datetime|None=None; tags:list[ContactTagOut]=[]
class ContactDetailOut(ContactListOut):
    message_count:int=0; notes:list[ContactNoteOut]=[]; custom_fields:list[ContactCustomFieldOut]=[]
class ContactUpdate(BaseModel): name:str|None=Field(default=None,max_length=200)
class ContactLifecycleUpdate(BaseModel): archived:bool|None=None; blocked:bool|None=None
class AgentOut(BaseModel):
    model_config=ConfigDict(from_attributes=True); id:int; email:str; name:str; role:UserRole; active:bool
class UserCreate(BaseModel): email:EmailStr; name:str=Field(min_length=2,max_length=150); password:str=Field(min_length=8,max_length=512); role:UserRole=UserRole.AGENT
class UserUpdate(BaseModel):
    name:str|None=Field(default=None,min_length=2,max_length=150); role:UserRole|None=None; active:bool|None=None; password:str|None=Field(default=None,min_length=8,max_length=512)
class ConversationOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int; phone_number_id:int; status:ConversationStatus; last_message_at:datetime|None; contact:ContactOut; unread_count:int=0; last_message_body:str|None=None; last_message_direction:MessageDirection|None=None; assigned_user_id:int|None=None; assigned_user:AgentOut|None=None
class ConversationStatusUpdate(BaseModel): status:ConversationStatus
class ConversationAssignmentUpdate(BaseModel): user_id:int|None=None
class MessageOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int; meta_message_id:str|None; direction:MessageDirection; message_type:str; body:str|None; status:MessageStatus; whatsapp_timestamp:datetime|None; created_at:datetime
class SendTextRequest(BaseModel): text:str=Field(min_length=1,max_length=4096)
class WhatsAppConnectionCreate(BaseModel):
    workspace_name:str=Field(min_length=2,max_length=150); workspace_slug:str=Field(min_length=2,max_length=150,pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"); waba_id:str=Field(min_length=2,max_length=64); phone_number_id:str=Field(min_length=2,max_length=64); access_token:str=Field(min_length=10)
    @field_validator("workspace_name","waba_id","phone_number_id","access_token")
    @classmethod
    def strip_required(cls,value:str)->str:
        value=value.strip()
        if not value: raise ValueError("Value cannot be blank")
        return value
class WhatsAppConnectionOut(BaseModel):
    id:int; workspace_id:int; workspace_name:str; workspace_slug:str; whatsapp_account_id:int; waba_id:str; account_name:str|None; phone_number_id:str; display_phone_number:str|None; verified_name:str|None; active:bool; has_access_token:bool
class WhatsAppConnectionVerify(BaseModel): waba_id:str=Field(min_length=2,max_length=64); phone_number_id:str=Field(min_length=2,max_length=64); access_token:str=Field(min_length=10)
class WhatsAppConnectionHealth(BaseModel):
    connected:bool; waba_id:str; account_name:str|None=None; phone_number_id:str; display_phone_number:str|None=None; verified_name:str|None=None; quality_rating:str|None=None; platform_type:str|None=None; code_verification_status:str|None=None
class WebhookSetupOut(BaseModel): callback_path:str; verify_token:str; app_secret_configured:bool
