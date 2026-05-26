"""JWT auth utilities adapted to JSON file storage."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request, status

from storage import get_by, list_items, save

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_DAYS = 7
ADMIN_FILE = "admin"


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(email: str) -> str:
    payload = {
        "sub": email,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_DAYS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])


def seed_admin() -> None:
    """Create the admin user on startup if it doesn't exist.

    Stored in /app/backend/data/admin.json as a single-element list. Idempotent:
    only re-hashes if the password actually changed.
    """
    email = os.environ.get("ADMIN_EMAIL", "admin@belarustours.by")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admins = list_items(ADMIN_FILE)
    existing = next((a for a in admins if a.get("email") == email), None)
    if existing is None:
        admins.append(
            {
                "email": email,
                "password_hash": hash_password(password),
                "name": "Administrator",
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        save(ADMIN_FILE, admins)
    elif not verify_password(password, existing["password_hash"]):
        for a in admins:
            if a.get("email") == email:
                a["password_hash"] = hash_password(password)
        save(ADMIN_FILE, admins)


def authenticate(email: str, password: str) -> dict | None:
    user = get_by(ADMIN_FILE, "email", email.lower().strip())
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {"email": user["email"], "name": user.get("name"), "role": user.get("role", "admin")}


async def get_current_admin(request: Request) -> dict:
    """Dependency: extract bearer token, return current admin user."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = auth[7:]
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    email = payload.get("email")
    user = get_by(ADMIN_FILE, "email", email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {"email": user["email"], "name": user.get("name"), "role": user.get("role", "admin")}
