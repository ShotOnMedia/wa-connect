import hashlib
import hmac
import httpx
from app.core.config import settings
class WhatsAppError(RuntimeError):pass
def verify_meta_signature(raw_body:bytes,signature_header:str|None)->bool:
    if not settings.meta_app_secret or not signature_header or not signature_header.startswith("sha256="):return False
    supplied=signature_header.removeprefix("sha256=")
    if len(supplied)!=64:return False
    expected=hmac.new(settings.meta_app_secret.encode(),raw_body,hashlib.sha256).hexdigest();return hmac.compare_digest(supplied.lower(),expected)
async def _graph_get(path,access_token,params=None):
    url=f"https://graph.facebook.com/{settings.meta_graph_api_version}/{path.lstrip('/')}";headers={"Authorization":f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:r=await client.get(url,headers=headers,params=params)
    if r.is_error:raise WhatsAppError(f"Meta API {r.status_code}: {r.text}")
    return r.json()
async def _send_message(phone_number_id,access_token,payload):
    url=f"https://graph.facebook.com/{settings.meta_graph_api_version}/{phone_number_id}/messages";headers={"Authorization":f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:r=await client.post(url,json=payload,headers=headers)
    if r.is_error:raise WhatsAppError(f"Meta API {r.status_code}: {r.text}")
    return r.json()
async def verify_whatsapp_connection(waba_id,phone_number_id,access_token):
    phone=await _graph_get(phone_number_id,access_token,{"fields":"id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status"});account=await _graph_get(waba_id,access_token,{"fields":"id,name"});numbers=await _graph_get(waba_id+"/phone_numbers",access_token,{"fields":"id"})
    if not any(str(i.get("id"))==str(phone_number_id) for i in numbers.get("data",[])):raise WhatsAppError("The supplied phone number does not belong to the supplied WhatsApp Business Account")
    return {"waba_id":str(account.get("id",waba_id)),"account_name":account.get("name"),"phone_number_id":str(phone.get("id",phone_number_id)),"display_phone_number":phone.get("display_phone_number"),"verified_name":phone.get("verified_name"),"quality_rating":phone.get("quality_rating"),"platform_type":phone.get("platform_type"),"code_verification_status":phone.get("code_verification_status")}
async def send_text_message(phone_number_id,access_token,to,text):return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"text","text":{"preview_url":False,"body":text}})
async def request_location_message(phone_number_id,access_token,to,text):
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"interactive","interactive":{"type":"location_request_message","body":{"text":str(text or 'Please share your current location.')[:1024]},"action":{"name":"send_location"}}})
async def send_location_message(phone_number_id,access_token,to,latitude,longitude,name=None,address=None):
    location={"latitude":float(latitude),"longitude":float(longitude)}
    if name:location["name"]=str(name)[:1000]
    if address:location["address"]=str(address)[:1000]
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"location","location":location})
async def send_reply_buttons(phone_number_id,access_token,to,text,buttons):
    actions=[]
    for i,b in enumerate(buttons[:3]):actions.append({"type":"reply","reply":{"id":str(b.get("value") or b.get("id") or f"option_{i+1}")[:256],"title":str(b.get("label") or f"Option {i+1}")[:20]}})
    if not actions:raise WhatsAppError("Interactive message requires at least one reply button")
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"interactive","interactive":{"type":"button","body":{"text":text},"action":{"buttons":actions}}})
async def send_list_message(phone_number_id,access_token,to,text,rows,button_text="Choose",section_title="Options"):
    items=[]
    for i,row in enumerate(rows[:10]):
        item={"id":str(row.get("value") or row.get("id") or f"option_{i+1}")[:200],"title":str(row.get("label") or f"Option {i+1}")[:24]};description=str(row.get("description") or "").strip()[:72]
        if description:item["description"]=description
        items.append(item)
    if not items:raise WhatsAppError("List message requires at least one row")
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"interactive","interactive":{"type":"list","body":{"text":text},"action":{"button":str(button_text or "Choose")[:20],"sections":[{"title":str(section_title or "Options")[:24],"rows":items}]}}})
async def send_product_message(phone_number_id,access_token,to,catalog_id,product_retailer_id,body=None,footer=None):
    interactive={"type":"product","action":{"catalog_id":str(catalog_id),"product_retailer_id":str(product_retailer_id)}}
    if body:interactive["body"]={"text":str(body)[:1024]}
    if footer:interactive["footer"]={"text":str(footer)[:60]}
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"interactive","interactive":interactive})
async def send_media_message(phone_number_id,access_token,to,media_type,media,caption=None,filename=None):
    wa_type={"image":"image","video":"video","audio":"audio","file":"document","document":"document"}.get(media_type)
    if not wa_type:raise WhatsAppError(f"Unsupported WhatsApp media type: {media_type}")
    media_obj={"link":media} if media.startswith(("http://","https://")) else {"id":media}
    if caption and wa_type!="audio":media_obj["caption"]=caption
    if filename and wa_type=="document":media_obj["filename"]=filename
    return await _send_message(phone_number_id,access_token,{"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":wa_type,wa_type:media_obj})