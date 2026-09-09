import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.services.media_storage import get_storage_setting, read_stored_media
router=APIRouter(tags=["inbound-media"])
_FILENAME=re.compile(r"^[a-f0-9]{32}\.[A-Za-z0-9]{1,8}$")
@router.get("/inbound-media/{filename}",include_in_schema=False)
def inbound_media(filename:str,db:Session=Depends(get_db)):
    if not _FILENAME.fullmatch(filename):raise HTTPException(status_code=404,detail="Image not found")
    configured=get_storage_setting(db)
    directories=[configured.local_path or settings.inbound_media_dir,settings.inbound_media_dir]
    for directory in dict.fromkeys(directories):
        candidate=Path(directory)/filename
        if candidate.is_file():return FileResponse(candidate,headers={"Cache-Control":"public, max-age=31536000, immutable"})
    if str(configured.provider or "").lower()=="s3":
        prefix=str(configured.s3_prefix or "").strip("/")
        key=f"{prefix}/{filename}" if prefix else filename
        try:
            stored=read_stored_media(db,"s3",key)
            return Response(content=stored.content,media_type=stored.content_type,headers={"Cache-Control":"public, max-age=31536000, immutable"})
        except Exception:
            pass
    raise HTTPException(status_code=404,detail="Image not found")
