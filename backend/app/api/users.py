from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, require_admin, require_manager
from app.models import User
from app.schemas import AgentOut, UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[AgentOut])
def list_users(_: User = Depends(require_manager), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.active.desc(), User.name.asc())).all())


@router.get("/agents", response_model=list[AgentOut])
def list_agents(_: User = Depends(require_manager), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name.asc())).all())


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password), role=payload.role, active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=AgentOut)
def update_user(user_id: int, payload: UserUpdate, current: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.role is not None:
        user.role = payload.role
    if payload.active is not None:
        if user.id == current.id and not payload.active:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        user.active = payload.active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user
