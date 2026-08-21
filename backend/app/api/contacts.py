from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Contact, Conversation, Message
from app.schemas import ContactDetailOut, ContactListOut, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactListOut])
def list_contacts(
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
):
    conversation_stats = (
        select(
            Conversation.contact_id.label("contact_id"),
            func.count(Conversation.id).label("conversation_count"),
            func.max(Conversation.last_message_at).label("last_message_at"),
        )
        .group_by(Conversation.contact_id)
        .subquery()
    )

    stmt = (
        select(Contact, conversation_stats.c.conversation_count, conversation_stats.c.last_message_at)
        .outerjoin(conversation_stats, conversation_stats.c.contact_id == Contact.id)
        .order_by(conversation_stats.c.last_message_at.desc(), Contact.name.asc(), Contact.wa_id.asc())
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Contact.name.ilike(term), Contact.wa_id.ilike(term)))

    rows = db.execute(stmt).all()
    return [
        ContactListOut(
            id=contact.id,
            wa_id=contact.wa_id,
            name=contact.name,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
            conversation_count=int(conversation_count or 0),
            last_message_at=last_message_at,
        )
        for contact, conversation_count, last_message_at in rows
    ]


@router.get("/{contact_id}", response_model=ContactDetailOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    conversation_count = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.contact_id == contact.id)
    ) or 0
    message_count = db.scalar(
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.contact_id == contact.id)
    ) or 0
    last_message_at = db.scalar(
        select(func.max(Conversation.last_message_at)).where(Conversation.contact_id == contact.id)
    )

    return ContactDetailOut(
        id=contact.id,
        wa_id=contact.wa_id,
        name=contact.name,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
        conversation_count=int(conversation_count),
        message_count=int(message_count),
        last_message_at=last_message_at,
    )


@router.patch("/{contact_id}", response_model=ContactDetailOut)
def update_contact(contact_id: int, payload: ContactUpdate, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    if payload.name is not None:
        contact.name = payload.name.strip() or None
        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)

    return get_contact(contact_id, db)
