from pydantic import BaseModel,Field
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_admin
from app.services.media_storage import get_storage_setting,encrypt_secret,test_storage

router=APIRouter(prefix="/settings/media-storage",tags=["Settings"],dependencies=[Depends(require_admin)])
class StorageUpdate(BaseModel):
    provider:str=Field(pattern="^(local|s3)$");local_path:str="/app/storage/inbound-media";public_base_url:str="";max_upload_mb:int=Field(default=25,ge=1,le=250)
    s3_endpoint_url:str="";s3_region:str="";s3_bucket:str="";s3_access_key:str="";s3_secret_key:str="";s3_prefix:str="";s3_use_ssl:bool=True;s3_path_style:bool=False

def output(row):
    return {"provider":row.provider,"local_path":row.local_path,"public_base_url":row.public_base_url or "","max_upload_mb":row.max_upload_mb,"s3_endpoint_url":row.s3_endpoint_url or "","s3_region":row.s3_region or "","s3_bucket":row.s3_bucket or "","s3_prefix":row.s3_prefix or "","s3_use_ssl":row.s3_use_ssl,"s3_path_style":row.s3_path_style,"has_access_key":bool(row.s3_access_key_enc),"has_secret_key":bool(row.s3_secret_key_enc)}
@router.get("")
def get_media_storage(db:Session=Depends(get_db)):return output(get_storage_setting(db))
@router.put("")
def update_media_storage(req:StorageUpdate,db:Session=Depends(get_db)):
    row=get_storage_setting(db);row.provider=req.provider;row.local_path=req.local_path.strip() or "/app/storage/inbound-media";row.public_base_url=req.public_base_url.strip() or None;row.max_upload_mb=req.max_upload_mb
    row.s3_endpoint_url=req.s3_endpoint_url.strip() or None;row.s3_region=req.s3_region.strip() or None;row.s3_bucket=req.s3_bucket.strip() or None;row.s3_prefix=req.s3_prefix.strip().strip("/") or None;row.s3_use_ssl=req.s3_use_ssl;row.s3_path_style=req.s3_path_style
    try:
        if req.s3_access_key.strip():row.s3_access_key_enc=encrypt_secret(req.s3_access_key.strip())
        if req.s3_secret_key.strip():row.s3_secret_key_enc=encrypt_secret(req.s3_secret_key.strip())
    except RuntimeError as exc:raise HTTPException(503,str(exc)) from exc
    if req.provider=="s3" and (not row.s3_bucket or not row.s3_access_key_enc or not row.s3_secret_key_enc):raise HTTPException(422,"Bucket, access key and secret key are required for S3 storage")
    db.commit();db.refresh(row);return output(row)
@router.post("/test")
def test_media_storage(db:Session=Depends(get_db)):
    try:return test_storage(db)
    except Exception as exc:raise HTTPException(502,f"Storage test failed: {exc}") from exc
