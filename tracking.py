"""Server-side conversion helpers.

Tokens are intentionally read only from environment variables, not from public
settings.json, because they must not be visible in the browser/admin API.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

import requests

from storage import load

logger = logging.getLogger("travelspace.tracking")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _sha256(value: Any) -> str | None:
    text = _text(value).lower()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _settings() -> dict:
    data = load("settings", default={})
    return data if isinstance(data, dict) else {}


def _first(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _event_id(lead: dict) -> str:
    return _first(lead.get("event_id"), lead.get("id"))


def send_server_conversion_events(lead: dict) -> None:
    """Send server-side events in the background after lead creation."""
    _send_meta_lead(lead)
    _send_tiktok_lead(lead)


def _send_meta_lead(lead: dict) -> None:
    settings = _settings()
    pixel_id = _first(
        os.environ.get("META_PIXEL_ID"),
        os.environ.get("FACEBOOK_PIXEL_ID"),
        settings.get("facebook_pixel_id"),
        settings.get("meta_pixel_id"),
    )
    access_token = _first(os.environ.get("META_ACCESS_TOKEN"), os.environ.get("FACEBOOK_ACCESS_TOKEN"))

    if not pixel_id or not access_token:
        return

    click_ids = lead.get("click_ids") if isinstance(lead.get("click_ids"), dict) else {}
    extra = lead.get("extra") if isinstance(lead.get("extra"), dict) else {}

    user_data = {
        "client_ip_address": lead.get("ip"),
        "client_user_agent": lead.get("user_agent"),
        "ph": [_sha256(lead.get("phone"))] if _sha256(lead.get("phone")) else None,
        "em": [_sha256(extra.get("email"))] if _sha256(extra.get("email")) else None,
        "external_id": [_sha256(lead.get("id"))] if _sha256(lead.get("id")) else None,
        "fbc": click_ids.get("fbc"),
        "fbp": click_ids.get("fbp"),
    }
    user_data = {k: v for k, v in user_data.items() if v}

    event = {
        "event_name": "Lead",
        "event_time": int(time.time()),
        "event_id": _event_id(lead),
        "action_source": "website",
        "event_source_url": lead.get("page_url") or lead.get("source_page"),
        "user_data": user_data,
        "custom_data": {
            "content_name": lead.get("tour"),
            "content_category": lead.get("form_type") or "lead",
            "content_ids": [lead.get("tour_slug")] if lead.get("tour_slug") else [],
        },
    }

    try:
        response = requests.post(
            f"https://graph.facebook.com/v20.0/{pixel_id}/events",
            params={"access_token": access_token},
            json={"data": [event]},
            timeout=8,
        )
        if response.status_code >= 300:
            logger.warning("Meta CAPI error: %s %s", response.status_code, response.text[:500])
    except Exception:
        logger.exception("Meta CAPI request failed")


def _send_tiktok_lead(lead: dict) -> None:
    settings = _settings()
    pixel_code = _first(
        os.environ.get("TIKTOK_PIXEL_CODE"),
        os.environ.get("TIKTOK_PIXEL_ID"),
        settings.get("tiktok_pixel_id"),
    )
    access_token = _first(os.environ.get("TIKTOK_ACCESS_TOKEN"))

    if not pixel_code or not access_token:
        return

    extra = lead.get("extra") if isinstance(lead.get("extra"), dict) else {}
    payload = {
        "event_source": "web",
        "event_source_id": pixel_code,
        "data": [
            {
                "event": "SubmitForm",
                "event_time": int(time.time()),
                "event_id": _event_id(lead),
                "page": {"url": lead.get("page_url") or lead.get("source_page")},
                "user": {
                    "phone": _sha256(lead.get("phone")),
                    "email": _sha256(extra.get("email")),
                    "ip": lead.get("ip"),
                    "user_agent": lead.get("user_agent"),
                },
                "properties": {
                    "content_type": "tour" if lead.get("tour_slug") else lead.get("form_type") or "lead",
                    "content_name": lead.get("tour"),
                    "content_id": lead.get("tour_slug"),
                },
            }
        ],
    }

    try:
        response = requests.post(
            "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            headers={"Access-Token": access_token, "Content-Type": "application/json"},
            json=payload,
            timeout=8,
        )
        if response.status_code >= 300:
            logger.warning("TikTok Events API error: %s %s", response.status_code, response.text[:500])
    except Exception:
        logger.exception("TikTok Events API request failed")
