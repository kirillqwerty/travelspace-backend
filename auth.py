"""Authentication helpers for the single Travelspace administrator.

The browser session is stored in a persistent HttpOnly cookie. Mutating
requests additionally require a CSRF token which is bound to that session.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request, status

from storage import get_by, list_items, save

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "travelspace-admin"
JWT_AUDIENCE = "travelspace-admin-panel"
ADMIN_FILE = "admin"
ADMIN_SESSION_COOKIE = "travelspace_admin_session"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

DEFAULT_ACCESS_TOKEN_MINUTES = 480
MAX_ACCESS_TOKEN_MINUTES = 1_440
# Browsers retain cookies for a finite period; /auth/me renews this lifetime.
# The signed persistent session itself does not expire and remains revocable.
ADMIN_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5

_PLACEHOLDER_MARKERS = (
    "change_me",
    "replace_me",
    "example.invalid",
    "your_",
    "mock_",
)
_login_failures: dict[str, deque[float]] = defaultdict(deque)
_login_failures_lock = threading.Lock()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise RuntimeError(f"{name} still contains a placeholder")
    return value


def _admin_email() -> str:
    email = _required_env("ADMIN_EMAIL").lower()
    if "@" not in email:
        raise RuntimeError("ADMIN_EMAIL must be a valid email address")
    return email


def _admin_password() -> str:
    password = _required_env("ADMIN_PASSWORD")
    if len(password) < 16:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 16 characters")
    return password


def _secret() -> str:
    value = _required_env("JWT_SECRET")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
    return value


def access_token_minutes() -> int:
    raw = os.environ.get(
        "ACCESS_TOKEN_MINUTES",
        str(DEFAULT_ACCESS_TOKEN_MINUTES),
    )
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise RuntimeError("ACCESS_TOKEN_MINUTES must be an integer") from exc
    if not 5 <= minutes <= MAX_ACCESS_TOKEN_MINUTES:
        raise RuntimeError(
            f"ACCESS_TOKEN_MINUTES must be between 5 and {MAX_ACCESS_TOKEN_MINUTES}"
        )
    return minutes


def persistent_admin_sessions() -> bool:
    return os.environ.get("ADMIN_SESSION_PERSISTENT", "true").strip().lower() == "true"


def validate_auth_configuration() -> None:
    """Fail startup when authentication still uses weak/default settings."""
    _admin_email()
    _admin_password()
    _secret()
    if not persistent_admin_sessions():
        access_token_minutes()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# This fixed hash makes an unknown-email attempt perform the same expensive
# bcrypt operation as a known-email attempt without creating a real account.
_DUMMY_PASSWORD_HASH = "$2b$12$3v0T62G2OcNtd5BmOrHN6eOQCvYcmUgw4BOfJB9xCz7uvTbP4pLwK"


def _public_user(user: dict, csrf_token: str | None = None) -> dict:
    result = {
        "email": user["email"],
        "name": user.get("name") or "Administrator",
        "role": "admin",
    }
    if csrf_token:
        result["csrf_token"] = csrf_token
    return result


def create_access_token(user: dict) -> tuple[str, str, int]:
    now = datetime.now(timezone.utc)
    csrf_token = secrets.token_urlsafe(32)
    persistent = persistent_admin_sessions()
    lifetime_seconds = ADMIN_COOKIE_MAX_AGE if persistent else access_token_minutes() * 60
    payload = {
        "sub": user["email"],
        "email": user["email"],
        "type": "access",
        "role": "admin",
        "ver": user["token_version"],
        "csrf": csrf_token,
        "jti": secrets.token_urlsafe(24),
        "iat": now,
        "nbf": now,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    if persistent:
        payload["persistent"] = True
    else:
        payload["exp"] = now + timedelta(seconds=lifetime_seconds)
    token = jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)
    return token, csrf_token, lifetime_seconds


def decode_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        _secret(),
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={
            "require": [
                "sub",
                "email",
                "type",
                "role",
                "ver",
                "csrf",
                "jti",
                "iat",
                "nbf",
                "iss",
                "aud",
            ]
        },
    )
    # Only explicitly issued persistent tokens may omit expiration. Legacy
    # timed tokens retain their original expiration and validation rules.
    if "exp" not in payload and payload.get("persistent") is not True:
        raise jwt.MissingRequiredClaimError("exp")
    if payload.get("persistent") is True and not persistent_admin_sessions():
        raise jwt.InvalidTokenError("Persistent sessions have been disabled")
    return payload


def seed_admin() -> None:
    """Create/update the one configured admin and remove stale accounts."""
    validate_auth_configuration()
    email = _admin_email()
    password = _admin_password()
    admins = list_items(ADMIN_FILE)
    existing = next(
        (item for item in admins if str(item.get("email", "")).lower() == email),
        None,
    )
    now = datetime.now(timezone.utc).isoformat()

    if existing is None:
        configured = {
            "email": email,
            "password_hash": hash_password(password),
            "name": "Administrator",
            "role": "admin",
            "active": True,
            "token_version": secrets.token_urlsafe(24),
            "created_at": now,
            "updated_at": now,
        }
    else:
        configured = dict(existing)
        configured.update(
            {
                "email": email,
                "name": configured.get("name") or "Administrator",
                "role": "admin",
                "active": True,
                "updated_at": now,
            }
        )
        password_changed = not verify_password(
            password,
            str(configured.get("password_hash", "")),
        )
        if password_changed:
            configured["password_hash"] = hash_password(password)
            configured["token_version"] = secrets.token_urlsafe(24)
        elif not configured.get("token_version"):
            configured["token_version"] = secrets.token_urlsafe(24)

    # The product currently has a single-administrator model. Saving only the
    # configured account also removes old default or forgotten accounts.
    save(ADMIN_FILE, [configured])


def authenticate(email: str, password: str) -> dict | None:
    normalized_email = email.lower().strip()
    configured_email = _admin_email()
    user = (
        get_by(ADMIN_FILE, "email", configured_email)
        if secrets.compare_digest(normalized_email, configured_email)
        else None
    )
    if not user:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, str(user.get("password_hash", ""))):
        return None
    if user.get("active") is not True or user.get("role") != "admin":
        return None
    if not user.get("token_version"):
        return None
    return user


def revoke_admin_tokens(email: str) -> None:
    admins = list_items(ADMIN_FILE)
    changed = False
    for user in admins:
        if str(user.get("email", "")).lower() == email.lower():
            user["token_version"] = secrets.token_urlsafe(24)
            user["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
    if changed:
        save(ADMIN_FILE, admins)


def _failure_keys(client_ip: str, email: str) -> tuple[str, str]:
    normalized_email = email.lower().strip()
    return f"ip:{client_ip}", f"account:{client_ip}:{normalized_email}"


def _prune_failures(attempts: deque[float], now: float) -> None:
    while attempts and now - attempts[0] >= LOGIN_WINDOW_SECONDS:
        attempts.popleft()


def login_retry_after(client_ip: str, email: str) -> int:
    now = time.monotonic()
    with _login_failures_lock:
        retry_after = 0
        for key in _failure_keys(client_ip, email):
            attempts = _login_failures[key]
            _prune_failures(attempts, now)
            if len(attempts) >= LOGIN_MAX_FAILURES:
                retry_after = max(
                    retry_after,
                    int(LOGIN_WINDOW_SECONDS - (now - attempts[0])) + 1,
                )
        return retry_after


def record_login_failure(client_ip: str, email: str) -> None:
    now = time.monotonic()
    with _login_failures_lock:
        for key in _failure_keys(client_ip, email):
            attempts = _login_failures[key]
            _prune_failures(attempts, now)
            attempts.append(now)


def clear_login_failures(client_ip: str, email: str) -> None:
    with _login_failures_lock:
        for key in _failure_keys(client_ip, email):
            _login_failures.pop(key, None)


def request_client_ip(request: Request) -> str:
    if os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


async def get_current_admin(request: Request) -> dict:
    """Validate the cookie session and enforce CSRF on mutating requests."""
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from exc

    email = str(payload.get("email", "")).lower()
    if (
        payload.get("type") != "access"
        or payload.get("role") != "admin"
        or payload.get("sub") != email
        or not secrets.compare_digest(email, _admin_email())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )

    user = get_by(ADMIN_FILE, "email", email)
    if (
        not user
        or user.get("active") is not True
        or user.get("role") != "admin"
        or not secrets.compare_digest(
            str(payload.get("ver", "")),
            str(user.get("token_version", "")),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked",
        )

    csrf_token = str(payload.get("csrf", ""))
    if request.method.upper() in UNSAFE_METHODS:
        supplied_csrf = request.headers.get(CSRF_HEADER, "")
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )

    return _public_user(user, csrf_token)
