import base64, hashlib, mimetypes
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import boto3
from botocore.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.storage_models import MediaStorageSetting

@dataclass
class StoredMedia:
    url:str
    key:str
    provider:str

def _fernet():
    secret=str(settings.media_settings_encryption_key or "").strip()
    if not secret: raise RuntimeError("MEDIA_SETTINGS_ENCRYPTION_KEY must be configured before S3 credentials can be saved")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
def encrypt_secret(value:str)->str:return _fernet().encrypt(value.encode()).decode()
def decrypt_secret(value:str|None)->str:return _fernet().decrypt(value.encode()).decode() if value else ""

def get_storage_setting(db:Session)->MediaStorageSetting:
    row=db.scalar(select(MediaStorageSetting).order_by(MediaStorageSetting.id.asc()))
    if row:return row
    row=MediaStorageSetting(provider="local",local_path=settings.inbound_media_dir,public_base_url=settings.public_base_url or None,max_upload_mb=25);db.add(row);db.flush();return row

def extension_for(content_type:str|None)->str:
    mime=str(content_type or "").split(";",1)[0].strip().lower();known={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif","image/heic":".heic","image/heif":".heif"};return known.get(mime) or mimetypes.guess_extension(mime) or ".bin"
def _base(row):return str(row.public_base_url or settings.public_base_url or "").strip().rstrip("/")
def _key(row,content_type):
    prefix=str(row.s3_prefix or "").strip("/");name=f"{uuid4().hex}{extension_for(content_type)}";return f"{prefix}/{name}" if prefix else name

def s3_client(row):
    return boto3.client("s3",endpoint_url=(row.s3_endpoint_url or None),region_name=(row.s3_region or None),aws_access_key_id=decrypt_secret(row.s3_access_key_enc),aws_secret_access_key=decrypt_secret(row.s3_secret_key_enc),use_ssl=bool(row.s3_use_ssl),config=Config(s3={"addressing_style":"path" if row.s3_path_style else "auto"}))

def store_media(db:Session,content:bytes,content_type:str|None)->StoredMedia:
    row=get_storage_setting(db);limit=max(1,int(row.max_upload_mb or 25))*1024*1024
    if not content:raise RuntimeError("Incoming media download returned an empty file")
    if len(content)>limit:raise RuntimeError(f"Incoming media is larger than the {row.max_upload_mb} MB storage limit")
    if row.provider=="s3":
        if not row.s3_bucket:raise RuntimeError("S3 bucket is not configured")
        key=_key(row,content_type);s3_client(row).put_object(Bucket=row.s3_bucket,Key=key,Body=content,ContentType=content_type or "application/octet-stream")
        base=_base(row)
        if base:url=f"{base}/{key}"
        elif row.s3_endpoint_url:url=f"{str(row.s3_endpoint_url).rstrip('/')}/{row.s3_bucket}/{key}"
        else:url=f"https://{row.s3_bucket}.s3.amazonaws.com/{key}"
        return StoredMedia(url,key,"s3")
    root=Path(row.local_path or settings.inbound_media_dir);root.mkdir(parents=True,exist_ok=True);key=f"{uuid4().hex}{extension_for(content_type)}";(root/key).write_bytes(content)
    path=f"{settings.api_prefix}/inbound-media/{key}";base=_base(row);return StoredMedia(f"{base}{path}" if base else path,key,"local")

def test_storage(db:Session):
    row=get_storage_setting(db)
    if row.provider=="s3":
        if not row.s3_bucket:raise RuntimeError("S3 bucket is required")
        client=s3_client(row);key=(str(row.s3_prefix or "").strip("/")+"/" if row.s3_prefix else "")+".wa-connect-storage-test";client.put_object(Bucket=row.s3_bucket,Key=key,Body=b"WA Connect storage test",ContentType="text/plain");client.delete_object(Bucket=row.s3_bucket,Key=key);return {"ok":True,"provider":"s3","message":f"Successfully wrote to {row.s3_bucket}."}
    root=Path(row.local_path or settings.inbound_media_dir);root.mkdir(parents=True,exist_ok=True);probe=root/".wa-connect-storage-test";probe.write_text("ok");probe.unlink();return {"ok":True,"provider":"local","message":f"Local storage is writable: {root}"}
