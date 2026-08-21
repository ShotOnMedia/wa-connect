from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.models import Contact, ContactNote, ContactTag, ContactTagLink, Conversation, Message, User
from app.schemas import ContactDetailOut, ContactListOut, ContactNoteCreate, ContactNoteOut, ContactTagCreate, ContactTagOut, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _tag_out(tag: ContactTag) -> ContactTagOut:
    return ContactTagOut(id=tag.id, name=tag.name)


def _note_out(note: ContactNote) -> ContactNoteOut:
    return ContactNoteOut(id=note.id, body=note.body, user_id=note.user_id, author_name=note.user.name, created_at=note.created_at, updated_at=note.updated_at)


def _detail(db: Session, contact: Contact) -> ContactDetailOut:
    conversation_count = db.scalar(select(func.count(Conversation.id)).where(Conversation.contact_id == contact.id)) or 0
    message_count = db.scalar(select(func.count(Message.id)).join(Conversation, Conversation.id == Message.conversation_id).where(Conversation.contact_id == contact.id)) or 0
    last_message_at = db.scalar(select(func.max(Conversation.last_message_at)).where(Conversation.contact_id == contact.id))
    db.refresh(contact)
    return ContactDetailOut(id=contact.id, wa_id=contact.wa_id, name=contact.name, created_at=contact.created_at, updated_at=contact.updated_at, conversation_count=int(conversation_count), message_count=int(message_count), last_message_at=last_message_at, tags=[_tag_out(tag) for tag in sorted(contact.tags, key=lambda t: t.name.lower())], notes=[_note_out(note) for note in contact.notes])


@router.get("", response_model=list[ContactListOut])
def list_contacts(q: str | None = Query(default=None, max_length=200), tag_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    conversation_stats = select(Conversation.contact_id.label("contact_id"), func.count(Conversation.id).label("conversation_count"), func.max(Conversation.last_message_at).label("last_message_at")).group_by(Conversation.contact_id).subquery()
    stmt = select(Contact, conversation_stats.c.conversation_count, conversation_stats.c.last_message_at).options(selectinload(Contact.tags)).outerjoin(conversation_stats, conversation_stats.c.contact_id == Contact.id).order_by(conversation_stats.c.last_message_at.desc(), Contact.name.asc(), Contact.wa_id.asc())
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Contact.name.ilike(term), Contact.wa_id.ilike(term)))
    if tag_id is not None:
        stmt = stmt.join(ContactTagLink, ContactTagLink.contact_id == Contact.id).where(ContactTagLink.tag_id == tag_id)
    rows = db.execute(stmt).all()
    return [ContactListOut(id=contact.id, wa_id=contact.wa_id, name=contact.name, created_at=contact.created_at, updated_at=contact.updated_at, conversation_count=int(conversation_count or 0), last_message_at=last_message_at, tags=[_tag_out(tag) for tag in sorted(contact.tags, key=lambda t: t.name.lower())]) for contact, conversation_count, last_message_at in rows]


@router.get("/tags", response_model=list[ContactTagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.scalars(select(ContactTag).order_by(ContactTag.name.asc())).all()


@router.post("/tags", response_model=ContactTagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: ContactTagCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tag name cannot be blank")
    workspace_id = db.scalar(select(Contact.workspace_id).limit(1))
    if workspace_id is None:
        raise HTTPException(status_code=400, detail="Create or receive a contact before creating tags")
    existing = db.scalar(select(ContactTag).where(ContactTag.workspace_id == workspace_id, func.lower(ContactTag.name) == name.lower()))
    if existing:
        return existing
    tag = ContactTag(workspace_id=workspace_id, name=name)
    db.add(tag); db.commit(); db.refresh(tag)
    return tag


@router.get("/{contact_id}", response_model=ContactDetailOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.scalar(select(Contact).options(selectinload(Contact.tags), selectinload(Contact.notes).selectinload(ContactNote.user)).where(Contact.id == contact_id))
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return _detail(db, contact)


@router.patch("/{contact_id}", response_model=ContactDetailOut)
def update_contact(contact_id: int, payload: ContactUpdate, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if payload.name is not None:
        contact.name = payload.name.strip() or None
        contact.updated_at = datetime.utcnow()
        db.commit()
    return get_contact(contact_id, db)


@router.post("/{contact_id}/tags/{tag_id}", response_model=ContactDetailOut)
def add_contact_tag(contact_id: int, tag_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id); tag = db.get(ContactTag, tag_id)
    if not contact or not tag:
        raise HTTPException(status_code=404, detail="Contact or tag not found")
    if contact.workspace_id != tag.workspace_id:
        raise HTTPException(status_code=400, detail="Tag belongs to another workspace")
    exists = db.scalar(select(ContactTagLink.id).where(ContactTagLink.contact_id == contact_id, ContactTagLink.tag_id == tag_id))
    if not exists:
        db.add(ContactTagLink(contact_id=contact_id, tag_id=tag_id)); contact.updated_at = datetime.utcnow(); db.commit()
    return get_contact(contact_id, db)


@router.delete("/{contact_id}/tags/{tag_id}", response_model=ContactDetailOut)
def remove_contact_tag(contact_id: int, tag_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    link = db.scalar(select(ContactTagLink).where(ContactTagLink.contact_id == contact_id, ContactTagLink.tag_id == tag_id))
    if link:
        db.delete(link); contact.updated_at = datetime.utcnow(); db.commit()
    return get_contact(contact_id, db)


@router.post("/{contact_id}/notes", response_model=ContactNoteOut, status_code=status.HTTP_201_CREATED)
def add_contact_note(contact_id: int, payload: ContactNoteCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Note cannot be blank")
    note = ContactNote(contact_id=contact_id, user_id=user.id, body=body)
    db.add(note); contact.updated_at = datetime.utcnow(); db.commit(); db.refresh(note)
    note.user = user
    return _note_out(note)


@router.delete("/{contact_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_note(contact_id: int, note_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    note = db.scalar(select(ContactNote).where(ContactNote.id == note_id, ContactNote.contact_id == contact_id))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != user.id and user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="You cannot delete this note")
    db.delete(note); db.commit()
