import json
from datetime import datetime,UTC,timedelta
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_manager
from app.campaign_engine_models import MessagingCampaign,MessagingCampaignStep,MessagingCampaignRecipient,MessagingCampaignDelivery,MessagingCampaignTemplate
from app.models import Workspace,WhatsAppAccount,WhatsAppPhoneNumber
from app.telegram_models import TelegramBot
from app.api.broadcasts import AudienceFilter,audience,field_values,_system_values,render,whatsapp_audience,whatsapp_field_values,whatsapp_system_values,whatsapp_render,render_provider_payload,unresolved_provider_tokens

router=APIRouter(prefix="/messaging-campaigns",tags=["Messaging Campaigns"],dependencies=[Depends(require_manager)])
def now():return datetime.now(UTC).replace(tzinfo=None)
def utc_naive(value):
    if value is None:return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
def token_fields(text):
    import re
    return [m.group(1) for m in re.finditer(r"%([a-zA-Z0-9_.-]+)%",text or "")]

class CampaignIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);channel:str;channel_account_id:int;description:str|None=None
    audience_type:str="all";audience_filter:dict|None=None;audience_segment_id:int|None=None;scheduled_at:datetime|None=None
class StepIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);delay_seconds:int=Field(default=0,ge=0,max=2592000)
    message_mode:str="freeform";message_text:str=Field(min_length=1,max_length=4096);provider_template:dict|None=None
    parse_mode:str="HTML";media_url:str|None=None;media_type:str|None=None

def workspace_for(db,channel,account_id):
    if channel=="telegram":
        wid=db.scalar(select(TelegramBot.workspace_id).where(TelegramBot.id==account_id))
    elif channel=="whatsapp":
        wid=db.scalar(select(WhatsAppAccount.workspace_id).join(WhatsAppPhoneNumber,WhatsAppPhoneNumber.whatsapp_account_id==WhatsAppAccount.id).where(WhatsAppPhoneNumber.id==account_id))
    else:raise HTTPException(400,"channel must be whatsapp or telegram")
    if wid is None:raise HTTPException(404,"Channel account not found")
    return wid
def step_out(s):return {"id":s.id,"position":s.position,"name":s.name,"delay_seconds":s.delay_seconds,"message_mode":s.message_mode,"message_text":s.message_text,"provider_template":json.loads(s.provider_template_json) if s.provider_template_json else None,"parse_mode":s.parse_mode,"media_url":s.media_url,"media_type":s.media_type,"created_at":s.created_at,"updated_at":s.updated_at}
def out(c,detail=False):
    recipients=getattr(c,"recipients",[]) or []
    data={"id":c.id,"name":c.name,"description":c.description,"channel":c.channel,"channel_account_id":c.channel_account_id,"status":c.status,"audience_type":c.audience_type,"audience_filter":json.loads(c.audience_filter_json) if c.audience_filter_json else None,"audience_segment_id":c.audience_segment_id,"scheduled_at":c.scheduled_at,"started_at":c.started_at,"completed_at":c.completed_at,"step_count":len(c.steps),"recipient_count":len(recipients),"completed_recipients":sum(1 for r in recipients if r.status=="completed"),"failed_recipients":sum(1 for r in recipients if r.status=="failed"),"created_at":c.created_at,"updated_at":c.updated_at}
    if detail:data["steps"]=[step_out(x) for x in c.steps]
    return data
def get(db,cid):
    c=db.get(MessagingCampaign,cid)
    if not c:raise HTTPException(404,"Campaign not found")
    return c

class CampaignTemplateIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);description:str|None=None

def template_out(t):
    steps=json.loads(t.steps_json or "[]")
    return {"id":t.id,"name":t.name,"description":t.description,"channel":t.channel,"step_count":len(steps),"steps":steps,"created_at":t.created_at,"updated_at":t.updated_at}

@router.get("/templates")
def template_listing(channel:str,db:Session=Depends(get_db),user=Depends(require_manager)):
    return [template_out(x) for x in db.scalars(select(MessagingCampaignTemplate).where(MessagingCampaignTemplate.channel==channel).order_by(MessagingCampaignTemplate.updated_at.desc())).all()]

@router.post("/{cid}/save-as-template")
def save_as_template(cid:int,body:CampaignTemplateIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    source=get(db,cid)
    steps=[{"name":s.name,"delay_seconds":s.delay_seconds,"message_mode":s.message_mode,"message_text":s.message_text,"provider_template":json.loads(s.provider_template_json) if s.provider_template_json else None,"parse_mode":s.parse_mode,"media_url":s.media_url,"media_type":s.media_type} for s in sorted(source.steps,key=lambda x:x.position)]
    if not steps:raise HTTPException(422,"Campaign must contain at least one message")
    t=MessagingCampaignTemplate(workspace_id=source.workspace_id,channel=source.channel,name=body.name.strip(),description=body.description,steps_json=json.dumps(steps),created_by_user_id=user.id,created_at=now(),updated_at=now())
    db.add(t);db.commit();db.refresh(t);return template_out(t)

@router.post("/templates/{tid}/create-campaign")
def create_from_template(tid:int,body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    t=db.get(MessagingCampaignTemplate,tid)
    if not t:raise HTTPException(404,"Campaign template not found")
    if body.channel!=t.channel:raise HTTPException(422,"Template channel does not match campaign channel")
    wid=workspace_for(db,body.channel,body.channel_account_id)
    c=MessagingCampaign(workspace_id=wid,channel=body.channel,channel_account_id=body.channel_account_id,name=body.name.strip(),description=body.description,status="draft",audience_type=body.audience_type,audience_filter_json=json.dumps(body.audience_filter) if body.audience_filter else None,audience_segment_id=body.audience_segment_id,created_by_user_id=user.id,created_at=now(),updated_at=now())
    db.add(c);db.flush()
    for pos,s in enumerate(json.loads(t.steps_json or "[]"),1):
        db.add(MessagingCampaignStep(campaign_id=c.id,position=pos,name=s["name"],delay_seconds=s.get("delay_seconds",0),message_mode=s.get("message_mode","freeform"),message_text=s["message_text"],provider_template_json=json.dumps(s.get("provider_template")) if s.get("provider_template") else None,parse_mode=s.get("parse_mode","HTML"),media_url=s.get("media_url"),media_type=s.get("media_type"),created_at=now(),updated_at=now()))
    db.commit();db.refresh(c);return out(c,True)

@router.put("/templates/{tid}")
def update_template(tid:int,body:CampaignTemplateIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    t=db.get(MessagingCampaignTemplate,tid)
    if not t:raise HTTPException(404,"Campaign template not found")
    t.name=body.name.strip();t.description=body.description;t.updated_at=now();db.commit();db.refresh(t);return template_out(t)

@router.delete("/templates/{tid}",status_code=204)
def delete_template(tid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    t=db.get(MessagingCampaignTemplate,tid)
    if not t:raise HTTPException(404,"Campaign template not found")
    db.delete(t);db.commit();return Response(status_code=204)

@router.get("")
def listing(channel:str|None=None,db:Session=Depends(get_db),user=Depends(require_manager)):
    q=select(MessagingCampaign)
    if channel:q=q.where(MessagingCampaign.channel==channel)
    return [out(x) for x in db.scalars(q.order_by(MessagingCampaign.updated_at.desc())).all()]
@router.post("")
def create(body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace_for(db,body.channel,body.channel_account_id)
    c=MessagingCampaign(workspace_id=wid,channel=body.channel,channel_account_id=body.channel_account_id,name=body.name.strip(),description=body.description,audience_type=body.audience_type,audience_filter_json=json.dumps(body.audience_filter) if body.audience_filter else None,audience_segment_id=body.audience_segment_id,scheduled_at=utc_naive(body.scheduled_at),created_by_user_id=user.id,created_at=now(),updated_at=now())
    db.add(c);db.commit();db.refresh(c);return out(c,True)
@router.get("/{cid}")
def detail(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):return out(get(db,cid),True)
@router.post("/{cid}/duplicate")
def duplicate(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    source=get(db,cid)
    clone=MessagingCampaign(
        workspace_id=source.workspace_id,channel=source.channel,channel_account_id=source.channel_account_id,
        name=(source.name+" — Copy")[:255],description=source.description,status="draft",
        audience_type=source.audience_type,audience_filter_json=source.audience_filter_json,
        audience_segment_id=source.audience_segment_id,scheduled_at=None,started_at=None,completed_at=None,
        created_by_user_id=user.id,created_at=now(),updated_at=now()
    )
    db.add(clone);db.flush()
    for step in sorted(source.steps,key=lambda x:x.position):
        db.add(MessagingCampaignStep(
            campaign_id=clone.id,position=step.position,name=step.name,delay_seconds=step.delay_seconds,
            message_mode=step.message_mode,message_text=step.message_text,
            provider_template_json=step.provider_template_json,parse_mode=step.parse_mode,
            media_url=step.media_url,media_type=step.media_type,created_at=now(),updated_at=now()
        ))
    db.commit();db.refresh(clone)
    return out(clone,True)

@router.put("/{cid}")
def update(cid:int,body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    wid=workspace_for(db,body.channel,body.channel_account_id)
    c.workspace_id=wid;c.channel=body.channel;c.channel_account_id=body.channel_account_id;c.name=body.name.strip();c.description=body.description;c.audience_type=body.audience_type;c.audience_filter_json=json.dumps(body.audience_filter) if body.audience_filter else None;c.audience_segment_id=body.audience_segment_id;c.scheduled_at=utc_naive(body.scheduled_at);c.updated_at=now()
    db.commit();db.refresh(c);return out(c,True)
@router.delete("/{cid}",status_code=204)
def delete(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be deleted")
    db.delete(c);db.commit();return Response(status_code=204)
@router.post("/{cid}/steps")
def add_step(cid:int,body:StepIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    position=max([x.position for x in c.steps],default=0)+1
    s=MessagingCampaignStep(campaign_id=c.id,position=position,name=body.name.strip(),delay_seconds=body.delay_seconds,message_mode=body.message_mode,message_text=body.message_text,provider_template_json=json.dumps(body.provider_template) if body.provider_template else None,parse_mode=body.parse_mode,media_url=body.media_url,media_type=body.media_type,created_at=now(),updated_at=now())
    db.add(s);db.commit();db.refresh(s);return step_out(s)
@router.put("/{cid}/steps/{sid}")
def update_step(cid:int,sid:int,body:StepIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=c.id:raise HTTPException(404,"Campaign step not found")
    s.name=body.name.strip();s.delay_seconds=body.delay_seconds;s.message_mode=body.message_mode;s.message_text=body.message_text;s.provider_template_json=json.dumps(body.provider_template) if body.provider_template else None;s.parse_mode=body.parse_mode;s.media_url=body.media_url;s.media_type=body.media_type;s.updated_at=now();db.commit();db.refresh(s);return step_out(s)
@router.delete("/{cid}/steps/{sid}",status_code=204)
def delete_step(cid:int,sid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=c.id:raise HTTPException(404,"Campaign step not found")
    pos=s.position;db.delete(s);db.flush()
    for x in db.scalars(select(MessagingCampaignStep).where(MessagingCampaignStep.campaign_id==cid,MessagingCampaignStep.position>pos).order_by(MessagingCampaignStep.position)).all():x.position-=1
    db.commit();return Response(status_code=204)
@router.post("/{cid}/steps/{sid}/move")
def move_step(cid:int,sid:int,direction:str,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=cid:raise HTTPException(404,"Campaign step not found")
    target=s.position+(-1 if direction=="up" else 1 if direction=="down" else 0)
    other=db.scalar(select(MessagingCampaignStep).where(MessagingCampaignStep.campaign_id==cid,MessagingCampaignStep.position==target))
    if other:
        tmp=-s.id;s.position=tmp;db.flush();other.position=s.position if False else (target+1 if direction=="up" else target-1);db.flush();s.position=target;db.commit()
    return out(c,True)


def _campaign_runtime_out(db,c):
    data=out(c,True)
    data["recipients"]=[{"id":r.id,"contact_id":r.channel_contact_id,"display_name":r.display_name,"destination":r.destination,"status":r.status,"current_step_position":r.current_step_position,"started_at":r.started_at,"completed_at":r.completed_at,"failed_at":r.failed_at,"last_error":r.last_error} for r in db.scalars(select(MessagingCampaignRecipient).where(MessagingCampaignRecipient.campaign_id==c.id).order_by(MessagingCampaignRecipient.id)).all()]
    data["deliveries"]=[{"id":d.id,"recipient_id":d.recipient_id,"step_id":d.step_id,"step_position":d.step_position,"status":d.status,"due_at":d.due_at,"attempts":d.attempts,"provider_message_id":d.provider_message_id,"sent_at":d.sent_at,"last_error":d.last_error} for d in db.scalars(select(MessagingCampaignDelivery).where(MessagingCampaignDelivery.campaign_id==c.id).order_by(MessagingCampaignDelivery.recipient_id,MessagingCampaignDelivery.step_position)).all()]
    return data

@router.get("/{cid}/runtime")
def runtime(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    return _campaign_runtime_out(db,get(db,cid))

@router.get("/{cid}/audience-preview")
def campaign_audience_preview(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    spec=AudienceFilter.model_validate(json.loads(c.audience_filter_json)) if c.audience_filter_json else None
    if c.channel=="telegram":
        rows=audience(db,c.workspace_id,c.channel_account_id,c.audience_type,[],spec)
        values_by_contact=field_values(db,[contact.id for contact,_ in rows])
    elif c.channel=="whatsapp":
        # Campaigns may mix template and free-form steps.  Do not discard
        # contacts merely because the service window is closed at preview
        # time; free-form eligibility is checked again when that step sends.
        rows=whatsapp_audience(db,c.workspace_id,c.channel_account_id,c.audience_type,[],spec,require_open_window=False)
        values_by_contact=whatsapp_field_values(db,[contact.id for contact,_ in rows])
    else:raise HTTPException(422,"Unsupported campaign channel")
    required=[]
    for step in c.steps:
        for key in token_fields(step.message_text):
            if key not in required:required.append(key)
    report=[];ready=0
    for contact,conv in rows:
        fields=values_by_contact.get(contact.id,{})
        values=(_system_values(contact) if c.channel=="telegram" else whatsapp_system_values(contact));values.update(fields)
        missing=[key for key in required if not str(values.get(key,"")).strip()]
        reasons=[{"code":"missing_field","field":key,"message":f"Missing value for %{key}%"} for key in missing]
        status="excluded" if reasons else "ready"
        preview_steps=[]
        for step in c.steps:
            rendered=(render(step.message_text,contact,fields) if c.channel=="telegram" else whatsapp_render(step.message_text,contact,fields))
            provider=json.loads(step.provider_template_json) if step.provider_template_json else None
            if provider:
                provider=render_provider_payload(provider,values)
                issues=unresolved_provider_tokens(provider)
                for issue in issues:
                    if not any(x.get("field")==issue["field"] for x in reasons):reasons.append({"code":"missing_field","field":issue["field"],"message":f"Missing value for %{issue['field']}%"})
            preview_steps.append({"id":step.id,"position":step.position,"name":step.name,"delay_seconds":step.delay_seconds,"message_mode":step.message_mode,"rendered_text":rendered,"provider_template":provider,"media_url":step.media_url,"media_type":step.media_type,"parse_mode":step.parse_mode})
        status="excluded" if reasons else "ready"
        destination=str(conv.chat_id) if c.channel=="telegram" else str(contact.wa_id)
        if status=="ready":ready+=1
        report.append({"contact_id":contact.id,"display_name":values["name"],"destination":destination,"status":status,"reasons":reasons,"preview_steps":preview_steps})
    return {"evaluated":len(report),"ready":ready,"excluded":len(report)-ready,"required_fields":required,"contacts":report}


@router.post("/{cid}/launch")
def launch(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be launched")
    if not c.steps:raise HTTPException(422,"Add at least one message before launching")
    spec=AudienceFilter.model_validate(json.loads(c.audience_filter_json)) if c.audience_filter_json else None
    if c.channel=="telegram":
        account=db.get(TelegramBot,c.channel_account_id)
        if not account or not account.active:raise HTTPException(400,"Telegram bot is unavailable")
        rows=audience(db,c.workspace_id,c.channel_account_id,c.audience_type,[],spec)
        values_by_contact=field_values(db,[contact.id for contact,_ in rows])
    elif c.channel=="whatsapp":
        account=db.get(WhatsAppPhoneNumber,c.channel_account_id)
        if not account or not account.active:raise HTTPException(400,"WhatsApp connection is unavailable")
        rows=whatsapp_audience(db,c.workspace_id,c.channel_account_id,c.audience_type,[],spec,require_open_window=False)
        values_by_contact=whatsapp_field_values(db,[contact.id for contact,_ in rows])
    else:raise HTTPException(422,"Unsupported campaign channel")
    if not rows:raise HTTPException(422,f"No eligible {c.channel.title()} recipients matched this campaign audience")
    required=[]
    for step in c.steps:
        for key in token_fields(step.message_text):
            if key not in required:required.append(key)
    eligible=[]
    for contact,conv in rows:
        fields=values_by_contact.get(contact.id,{})
        values=(_system_values(contact) if c.channel=="telegram" else whatsapp_system_values(contact));values.update(fields)
        if any(not str(values.get(key,"")).strip() for key in required):continue
        bad_template=False
        for step in c.steps:
            if step.provider_template_json and unresolved_provider_tokens(render_provider_payload(json.loads(step.provider_template_json),values)):bad_template=True;break
        if bad_template:continue
        eligible.append((contact,conv,fields,values))
    if not eligible:raise HTTPException(422,"No recipients passed campaign audience validation")
    launch_at=c.scheduled_at if c.scheduled_at and c.scheduled_at>now() else now()
    first=c.steps[0]
    for contact,conv,fields,values in eligible:
        destination=str(conv.chat_id) if c.channel=="telegram" else str(contact.wa_id)
        recipient=MessagingCampaignRecipient(campaign_id=c.id,channel_contact_id=contact.id,conversation_id=conv.id,destination=destination,display_name=values["name"],field_values_json=json.dumps(values),status="pending",current_step_position=1,created_at=now(),updated_at=now())
        db.add(recipient);db.flush()
        rendered=render(first.message_text,contact,fields) if c.channel=="telegram" else whatsapp_render(first.message_text,contact,fields)
        db.add(MessagingCampaignDelivery(campaign_id=c.id,recipient_id=recipient.id,step_id=first.id,step_position=first.position,rendered_text=rendered,media_url=first.media_url,media_type=first.media_type,parse_mode=first.parse_mode,status="pending",due_at=launch_at+timedelta(seconds=first.delay_seconds),created_at=now(),updated_at=now()))
    c.status="scheduled" if launch_at>now() else "running";c.started_at=None if launch_at>now() else now();c.updated_at=now()
    db.commit();db.refresh(c);return _campaign_runtime_out(db,c)

@router.post("/{cid}/pause")
def pause(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status not in ("running","scheduled"):raise HTTPException(409,"Only running or scheduled campaigns can be paused")
    c.status="paused";c.updated_at=now();db.commit();db.refresh(c);return out(c,True)

@router.post("/{cid}/resume")
def resume(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="paused":raise HTTPException(409,"Only paused campaigns can be resumed")
    c.status="running";c.started_at=c.started_at or now();c.updated_at=now();db.commit();db.refresh(c);return out(c,True)

@router.post("/{cid}/cancel")
def cancel(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status in ("completed","cancelled"):raise HTTPException(409,"Campaign is already finished")
    if c.status=="draft":raise HTTPException(409,"Delete a draft campaign instead of cancelling it")
    c.status="cancelled";c.updated_at=now()
    for d in db.scalars(select(MessagingCampaignDelivery).where(MessagingCampaignDelivery.campaign_id==c.id,MessagingCampaignDelivery.status=="pending")).all():d.status="cancelled";d.updated_at=now()
    db.commit();db.refresh(c);return out(c,True)
