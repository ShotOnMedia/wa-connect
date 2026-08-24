from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin
from app.models import WhatsAppAccount, WhatsAppPhoneNumber, Workspace
from app.schemas import (
    WebhookSetupOut,
    WhatsAppConnectionCreate,
    WhatsAppConnectionHealth,
    WhatsAppConnectionOut,
    WhatsAppConnectionVerify,
)
from app.services.whatsapp import WhatsAppError, verify_whatsapp_connection

router = APIRouter(prefix="/settings", tags=["Settings"], dependencies=[Depends(require_admin)])


def connection_out(phone: WhatsAppPhoneNumber) -> WhatsAppConnectionOut:
    return WhatsAppConnectionOut(
        id=phone.id,
        workspace_id=phone.account.workspace.id,
        workspace_name=phone.account.workspace.name,
        workspace_slug=phone.account.workspace.slug,
        whatsapp_account_id=phone.account.id,
        waba_id=phone.account.waba_id,
        account_name=phone.account.name,
        phone_number_id=phone.phone_number_id,
        display_phone_number=phone.display_phone_number,
        verified_name=phone.verified_name,
        active=phone.active and phone.account.active and phone.account.workspace.active,
        has_access_token=bool(phone.access_token),
    )


@router.get("/whatsapp", response_model=list[WhatsAppConnectionOut])
def list_whatsapp_connections(db: Session = Depends(get_db)):
    stmt = select(WhatsAppPhoneNumber).options(selectinload(WhatsAppPhoneNumber.account).selectinload(WhatsAppAccount.workspace)).order_by(WhatsAppPhoneNumber.created_at.asc())
    return [connection_out(phone) for phone in db.scalars(stmt).all()]


@router.get("/whatsapp/webhook", response_model=WebhookSetupOut)
def webhook_setup():
    return WebhookSetupOut(
        callback_path=f"{settings.api_prefix}/webhooks/meta/whatsapp",
        verify_token=settings.meta_verify_token,
        app_secret_configured=bool(settings.meta_app_secret),
    )


@router.post("/whatsapp/verify", response_model=WhatsAppConnectionHealth)
async def verify_connection(request: WhatsAppConnectionVerify):
    try:
        result = await verify_whatsapp_connection(request.waba_id.strip(), request.phone_number_id.strip(), request.access_token.strip())
        return WhatsAppConnectionHealth(connected=True, **result)
    except WhatsAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/whatsapp/{connection_id}/health", response_model=WhatsAppConnectionHealth)
async def connection_health(connection_id: int, db: Session = Depends(get_db)):
    phone = db.scalar(select(WhatsAppPhoneNumber).options(selectinload(WhatsAppPhoneNumber.account)).where(WhatsAppPhoneNumber.id == connection_id))
    if not phone:
        raise HTTPException(status_code=404, detail="WhatsApp connection not found")
    access_token = phone.access_token or settings.meta_access_token
    if not access_token:
        raise HTTPException(status_code=503, detail="No WhatsApp access token configured")
    try:
        result = await verify_whatsapp_connection(phone.account.waba_id, phone.phone_number_id, access_token)
        phone.display_phone_number = result.get("display_phone_number") or phone.display_phone_number
        phone.verified_name = result.get("verified_name") or phone.verified_name
        phone.account.name = result.get("account_name") or phone.account.name
        db.commit()
        return WhatsAppConnectionHealth(connected=True, **result)
    except WhatsAppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/whatsapp", response_model=WhatsAppConnectionOut, status_code=201)
async def create_whatsapp_connection(request: WhatsAppConnectionCreate, db: Session = Depends(get_db)):
    waba_id = request.waba_id.strip()
    phone_number_id = request.phone_number_id.strip()
    access_token = request.access_token.strip()

    try:
        meta = await verify_whatsapp_connection(waba_id, phone_number_id, access_token)
    except WhatsAppError as exc:
        raise HTTPException(status_code=502, detail=f"Meta verification failed: {exc}") from exc

    # Credential rotation: if this phone number is already connected, a successful
    # Meta verification means the supplied token is valid. Update the existing
    # connection instead of rejecting it as a duplicate.
    existing_phone = db.scalar(
        select(WhatsAppPhoneNumber)
        .options(selectinload(WhatsAppPhoneNumber.account).selectinload(WhatsAppAccount.workspace))
        .where(WhatsAppPhoneNumber.phone_number_id == phone_number_id)
    )
    if existing_phone:
        account = existing_phone.account
        if account.waba_id != meta["waba_id"]:
            raise HTTPException(status_code=409, detail="This phone number is connected to a different WhatsApp Business Account")

        account.name = meta.get("account_name") or account.name
        existing_phone.display_phone_number = meta.get("display_phone_number") or existing_phone.display_phone_number
        existing_phone.verified_name = meta.get("verified_name") or existing_phone.verified_name
        existing_phone.access_token = access_token
        existing_phone.active = True
        db.commit()
        db.refresh(existing_phone)
        return connection_out(existing_phone)

    workspace = db.scalar(select(Workspace).where(Workspace.slug == request.workspace_slug))
    if not workspace:
        workspace = Workspace(name=request.workspace_name, slug=request.workspace_slug)
        db.add(workspace)
        db.flush()

    account = db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.workspace_id == workspace.id, WhatsAppAccount.waba_id == meta["waba_id"]))
    if not account:
        account = WhatsAppAccount(workspace_id=workspace.id, waba_id=meta["waba_id"], name=meta.get("account_name"))
        db.add(account)
        db.flush()
    else:
        account.name = meta.get("account_name") or account.name

    phone = WhatsAppPhoneNumber(
        whatsapp_account_id=account.id,
        phone_number_id=meta["phone_number_id"],
        display_phone_number=meta.get("display_phone_number"),
        verified_name=meta.get("verified_name"),
        access_token=access_token,
    )
    db.add(phone)
    db.commit()
    db.refresh(phone)
    phone.account = account
    account.workspace = workspace
    return connection_out(phone)
