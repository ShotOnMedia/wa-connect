import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_manager
from app.http_api_models import HttpApi, HttpApiCall
from app.models import User
from app.services.http_api_executor import execute_http_api

router = APIRouter(prefix="/http-apis", tags=["HTTP APIs"])


class HttpApiPayload(BaseModel):
    name: str
    description: str | None = None
    method: str = "GET"
    endpoint_url: str
    headers: list[dict[str, Any]] = Field(default_factory=list)
    query: list[dict[str, Any]] = Field(default_factory=list)
    cookies: list[dict[str, Any]] = Field(default_factory=list)
    body_type: str = "none"
    body: Any = None
    response_mappings: list[dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: int = 15
    active: bool = True


def _loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _dump(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _row(x: HttpApi):
    return {"id":x.id,"name":x.name,"description":x.description,"method":x.method,"endpoint_url":x.endpoint_url,"headers":_loads(x.headers_json,[]),"query":_loads(x.query_json,[]),"cookies":_loads(x.cookies_json,[]),"body_type":x.body_type,"body":_loads(x.body_json,None),"response_mappings":_loads(x.response_mappings_json,[]),"timeout_seconds":x.timeout_seconds,"active":x.active,"verified":x.verified,"total_calls":x.total_calls,"total_success":x.total_success,"total_error":x.total_error,"last_called_at":x.last_called_at,"created_at":x.created_at,"updated_at":x.updated_at}


def _apply(x: HttpApi, p: HttpApiPayload):
    x.name=p.name.strip(); x.description=p.description; x.method=p.method.upper(); x.endpoint_url=p.endpoint_url.strip(); x.headers_json=_dump(p.headers); x.query_json=_dump(p.query); x.cookies_json=_dump(p.cookies); x.body_type=str(p.body_type or "none").lower(); x.body_json=_dump(p.body); x.response_mappings_json=_dump(p.response_mappings); x.timeout_seconds=max(1,min(120,p.timeout_seconds)); x.active=p.active; x.updated_at=datetime.utcnow()


@router.get("")
def list_http_apis(db:Session=Depends(get_db), _:User=Depends(require_manager)):
    return [_row(x) for x in db.scalars(select(HttpApi).order_by(HttpApi.name)).all()]


@router.post("")
def create_http_api(payload:HttpApiPayload, db:Session=Depends(get_db), _:User=Depends(require_manager)):
    x=HttpApi(created_at=datetime.utcnow(),updated_at=datetime.utcnow()); _apply(x,payload); db.add(x); db.commit(); db.refresh(x); return _row(x)


@router.get("/{api_id}")
def get_http_api(api_id:int, db:Session=Depends(get_db), _:User=Depends(require_manager)):
    x=db.get(HttpApi,api_id)
    if not x: raise HTTPException(404,"HTTP API not found")
    return _row(x)


@router.put("/{api_id}")
def update_http_api(api_id:int,payload:HttpApiPayload,db:Session=Depends(get_db),_:User=Depends(require_manager)):
    x=db.get(HttpApi,api_id)
    if not x: raise HTTPException(404,"HTTP API not found")
    _apply(x,payload); db.commit(); db.refresh(x); return _row(x)


@router.delete("/{api_id}")
def delete_http_api(api_id:int,db:Session=Depends(get_db),_:User=Depends(require_manager)):
    x=db.get(HttpApi,api_id)
    if not x: raise HTTPException(404,"HTTP API not found")
    db.delete(x); db.commit(); return {"ok":True}


@router.post("/{api_id}/test")
async def test_http_api(api_id:int,db:Session=Depends(get_db),_:User=Depends(require_manager)):
    x=db.get(HttpApi,api_id)
    if not x: raise HTTPException(404,"HTTP API not found")
    result=await execute_http_api(db,x,lambda value:value,apply_mappings=False)
    x.verified=bool(result["success"])
    db.commit()
    return result


@router.get("/{api_id}/calls")
def calls(api_id:int,db:Session=Depends(get_db),_:User=Depends(require_manager)):
    rows=db.scalars(select(HttpApiCall).where(HttpApiCall.http_api_id==api_id).order_by(HttpApiCall.created_at.desc()).limit(100)).all()
    return [{"id":x.id,"status_code":x.status_code,"success":x.success,"duration_ms":x.duration_ms,"error_message":x.error_message,"response_preview":x.response_preview,"created_at":x.created_at} for x in rows]
