import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Response, status
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models import User, UserRole, UserSession

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(days=settings.auth_session_days)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token), expires_at=expires_at))
    user.last_login_at = datetime.utcnow()
    db.commit()
    response.set_cookie(key=settings.auth_cookie_name, value=token, max_age=settings.auth_session_days * 86400, httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/")


def destroy_session(db: Session, response: Response, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/", secure=settings.auth_cookie_secure, samesite="lax")


def require_user(db: Session = Depends(get_db), session_token: str | None = Cookie(default=None, alias=settings.auth_cookie_name)) -> User:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session = db.scalar(select(UserSession).options(selectinload(UserSession.user)).where(UserSession.token_hash == _token_hash(session_token)))
    if not session or session.expires_at <= datetime.utcnow() or not session.user.active:
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    session.last_seen_at = datetime.utcnow()
    db.commit()
    return session.user


def require_manager(user: User = Depends(require_user)) -> User:
    if user.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager access required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def ensure_bootstrap_admin(db: Session) -> None:
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return
    email = settings.bootstrap_admin_email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return
    db.add(User(email=email, name=settings.bootstrap_admin_name.strip() or "Administrator", password_hash=hash_password(settings.bootstrap_admin_password), role=UserRole.ADMIN, active=True))
    db.commit()
