from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import WhatsAppAccount, WhatsAppPhoneNumber, Workspace
from app.schemas import WhatsAppConnectionCreate, WhatsAppConnectionOut

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/whatsapp", response_model=list[WhatsAppConnectionOut])
def list_whatsapp_connections(db: Session = Depends(get_db)):
    stmt = (
        select(WhatsAppPhoneNumber)
        .options(
            selectinload(WhatsAppPhoneNumber.account).selectinload(WhatsAppAccount.workspace)
        )
        .order_by(WhatsAppPhoneNumber.created_at.asc())
    )
    return [
        WhatsAppConnectionOut(
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
        for phone in db.scalars(stmt).all()
    ]


@router.post("/whatsapp", response_model=WhatsAppConnectionOut, status_code=201)
def create_whatsapp_connection(request: WhatsAppConnectionCreate, db: Session = Depends(get_db)):
    existing_phone = db.scalar(
        select(WhatsAppPhoneNumber).where(WhatsAppPhoneNumber.phone_number_id == request.phone_number_id)
    )
    if existing_phone:
        raise HTTPException(status_code=409, detail="This WhatsApp phone number ID is already connected")

    workspace = db.scalar(select(Workspace).where(Workspace.slug == request.workspace_slug))
    if not workspace:
        workspace = Workspace(name=request.workspace_name, slug=request.workspace_slug)
        db.add(workspace)
        db.flush()

    account = db.scalar(
        select(WhatsAppAccount).where(
            WhatsAppAccount.workspace_id == workspace.id,
            WhatsAppAccount.waba_id == request.waba_id,
        )
    )
    if not account:
        account = WhatsAppAccount(
            workspace_id=workspace.id,
            waba_id=request.waba_id,
            name=request.account_name or None,
        )
        db.add(account)
        db.flush()

    phone = WhatsAppPhoneNumber(
        whatsapp_account_id=account.id,
        phone_number_id=request.phone_number_id,
        display_phone_number=request.display_phone_number or None,
        verified_name=request.verified_name or None,
        access_token=request.access_token,
    )
    db.add(phone)
    db.commit()
    db.refresh(phone)

    return WhatsAppConnectionOut(
        id=phone.id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_slug=workspace.slug,
        whatsapp_account_id=account.id,
        waba_id=account.waba_id,
        account_name=account.name,
        phone_number_id=phone.phone_number_id,
        display_phone_number=phone.display_phone_number,
        verified_name=phone.verified_name,
        active=True,
        has_access_token=bool(phone.access_token),
    )
