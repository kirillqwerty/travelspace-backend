"""Isolated authentication checks; no real storage, server startup or leads."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
import json

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request

import auth
import server


@pytest.fixture
def admin(monkeypatch):
    user = {"email": "admin@example.com", "name": "Test admin", "active": True,
            "role": "admin", "token_version": "isolated-version"}
    records = [user]
    monkeypatch.setenv("JWT_SECRET", "isolated-auth-test-secret-" * 3)
    monkeypatch.setenv("ADMIN_EMAIL", user["email"])
    monkeypatch.setenv("ADMIN_SESSION_PERSISTENT", "true")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setattr(auth, "get_by", lambda *args: deepcopy(records[0]))
    monkeypatch.setattr(auth, "list_items", lambda *args: deepcopy(records))
    monkeypatch.setattr(auth, "save", lambda name, data: records.__setitem__(slice(None), deepcopy(data)))
    monkeypatch.setattr(server, "authenticate", lambda *args: deepcopy(records[0]))
    monkeypatch.setattr(server, "login_retry_after", lambda *args: 0)
    monkeypatch.setattr(server, "clear_login_failures", lambda *args: None)
    return user, records


def request(token, method="GET", csrf=None):
    headers = [(b"cookie", f"{auth.ADMIN_SESSION_COOKIE}={token}".encode())]
    if csrf is not None:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({"type": "http", "method": method, "headers": headers})


def test_persistent_session_has_no_server_expiration_even_after_years(admin, monkeypatch):
    class OldClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) - timedelta(days=3650)

    monkeypatch.setattr(auth, "datetime", OldClock)
    token, csrf, cookie_age = auth.create_access_token(admin[0])
    payload = auth.decode_token(token)
    assert payload["persistent"] is True
    assert "exp" not in payload
    assert cookie_age == auth.ADMIN_COOKIE_MAX_AGE
    assert asyncio.run(auth.get_current_admin(request(token, "PUT", csrf)))["email"] == admin[0]["email"]


def test_persistent_session_still_requires_csrf_and_is_revoked(admin):
    token, csrf, _ = auth.create_access_token(admin[0])
    for supplied in (None, "wrong"):
        with pytest.raises(HTTPException) as error:
            asyncio.run(auth.get_current_admin(request(token, "PUT", supplied)))
        assert error.value.status_code == 403
    auth.revoke_admin_tokens(admin[0]["email"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.get_current_admin(request(token, "PUT", csrf)))
    assert error.value.status_code == 401


def test_tokens_cannot_omit_exp_without_explicit_persistent_claim(admin):
    token, _, _ = auth.create_access_token(admin[0])
    payload = auth.decode_token(token)
    payload.pop("persistent")
    invalid = jwt.encode(payload, auth._secret(), algorithm=auth.JWT_ALGORITHM)
    with pytest.raises(jwt.MissingRequiredClaimError):
        auth.decode_token(invalid)
    payload["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = jwt.encode(payload, auth._secret(), algorithm=auth.JWT_ALGORITHM)
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.decode_token(expired)


def test_timed_mode_remains_available_and_rejects_persistent_tokens(admin, monkeypatch):
    persistent, _, _ = auth.create_access_token(admin[0])
    monkeypatch.setenv("ADMIN_SESSION_PERSISTENT", "false")
    monkeypatch.setenv("ACCESS_TOKEN_MINUTES", "30")
    token, _, age = auth.create_access_token(admin[0])
    assert "exp" in auth.decode_token(token)
    assert age == 1800
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(persistent)


def test_cookie_survives_reopen_is_renewed_and_logout_revokes_it(admin):
    app = FastAPI()
    app.post("/api/auth/login")(server.login)
    app.get("/api/auth/me")(server.me)
    app.post("/api/auth/logout")(server.logout)

    async def call(method, path, token=None, csrf=None, payload=None):
        headers = [(b"content-type", b"application/json")]
        if token:
            headers.append((b"cookie", f"{auth.ADMIN_SESSION_COOKIE}={token}".encode()))
        if csrf:
            headers.append((b"x-csrf-token", csrf.encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "root_path": "", "headers": headers,
                 "client": ("127.0.0.1", 12345), "server": ("local.test", 443)}
        messages = []
        async def receive():
            return {"type": "http.request", "body": json.dumps(payload).encode() if payload else b"", "more_body": False}
        async def send(message):
            messages.append(message)
        await app(scope, receive, send)
        response_headers = {key.decode(): value.decode() for key, value in messages[0]["headers"]}
        body = b"".join(message.get("body", b"") for message in messages[1:])
        return messages[0]["status"], response_headers, json.loads(body)

    async def run():
        status, headers, body = await call("POST", "/api/auth/login", payload={"email": admin[0]["email"], "password": "local-only-password"})
        assert status == 200
        csrf = body["csrf_token"]
        cookie = headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api", f"Max-Age={auth.ADMIN_COOKIE_MAX_AGE}"):
            assert attribute in cookie
        token = SimpleCookie(cookie)[auth.ADMIN_SESSION_COOKIE].value
        status, headers, body = await call("GET", "/api/auth/me", token)
        assert status == 200
        assert body["csrf_token"] == csrf
        assert f"Max-Age={auth.ADMIN_COOKIE_MAX_AGE}" in headers["set-cookie"]
        assert SimpleCookie(headers["set-cookie"])[auth.ADMIN_SESSION_COOKIE].value == token
        assert (await call("POST", "/api/auth/logout", token))[0] == 403
        status, headers, _ = await call("POST", "/api/auth/logout", token, csrf)
        assert status == 200
        assert "Max-Age=0" in headers["set-cookie"]
        assert (await call("GET", "/api/auth/me", token))[0] == 401
    asyncio.run(run())
