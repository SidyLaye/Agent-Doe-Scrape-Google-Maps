from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User


password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    return password_hash.verify(value, hashed)


def create_token(user: User) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": str(user.id), "email": user.email, "role": user.role, "exp": expires}, settings.jwt_secret, algorithm="HS256")


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(401, "Session invalide ou expirée", headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Compte indisponible")
    return user


def user_from_token(token: str, db: Session) -> User | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user = db.get(User, int(payload["sub"]))
        return user if user and user.is_active else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def ensure_initial_admin(db: Session) -> None:
    settings = get_settings()
    email = settings.initial_admin_email.strip().lower()
    password = settings.initial_admin_password
    if not email or not password:
        return
    if not db.scalar(select(User).where(User.email == email)):
        db.add(User(email=email, password_hash=hash_password(password), role="admin"))
        db.commit()
