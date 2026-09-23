from datetime import datetime
from fastapi import APIRouter,Depends,File,HTTPException,UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_manager
from app.services.media_storage import get_storage_setting,store_media
from app.storage_models import MediaAsset
from app.telegram_models import TelegramBot

router=APIRouter(prefix="/media-assets",tags=["Media Assets"],dependencies=[Depends(require_manager)])

def workspace_for_bot(db:Session,bot_id:int)->int:
    wid=db.scalar(select(TelegramBot.workspace_id).where(TelegramBot.id==bot_id,TelegramBot.active.is_(True)))
    if wid is None:raise HTTPException(404,"Telegram bot not found")
    return int(wid)
def output(a):
    return {"id":a.id,"name":a.name,"content_type":a.content_type,"media_type":a.media_type,"size_bytes":a.size_bytes,"url":a.url,"created_at":a.created_at}
def kind(content_type:str)->str:
    ct=(content_type or "").lower()
    if ct.startswith("image/"):return "image"
    if ct.startswith("video/"):return "video"
    return "file"

@router.get("")
def list_assets(bot_id:int,db:Session=Depends(get_db)):
    wid=workspace_for_bot(db,bot_id)
    rows=db.scalars(select(MediaAsset).where(MediaAsset.workspace_id==wid).order_by(MediaAsset.created_at.desc()).limit(200)).all()
    return [output(x) for x in rows]

@router.post("")
async def upload_asset(bot_id:int,file:UploadFile=File(...),db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace_for_bot(db,bot_id);setting=get_storage_setting(db)
    limit=max(1,int(setting.max_upload_mb or 25))*1024*1024
    data=await file.read(limit+1)
    if not data:raise HTTPException(422,"The selected file is empty")
    if len(data)>limit:raise HTTPException(413,f"File exceeds the {setting.max_upload_mb} MB media storage limit")
    content_type=str(file.content_type or "application/octet-stream")
    try:stored=store_media(db,data,content_type)
    except Exception as exc:raise HTTPException(502,f"Could not store media: {exc}") from exc
    asset=MediaAsset(workspace_id=wid,name=(file.filename or "media")[:255],content_type=content_type,media_type=kind(content_type),size_bytes=len(data),provider=stored.provider,storage_key=stored.key,url=stored.url,created_by_user_id=user.id,created_at=datetime.utcnow())
    db.add(asset);db.commit();db.refresh(asset);return output(asset)
