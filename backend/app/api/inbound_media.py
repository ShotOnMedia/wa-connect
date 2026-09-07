import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(tags=["inbound-media"])
_FILENAME = re.compile(r"^[a-f0-9]{32}\.[A-Za-z0-9]{1,8}$")


@router.get("/inbound-media/{filename}", include_in_schema=False)
def inbound_media(filename: str):
    if not _FILENAME.fullmatch(filename):
        raise HTTPException(status_code=404, detail="Image not found")
    root = Path(settings.inbound_media_dir).resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
