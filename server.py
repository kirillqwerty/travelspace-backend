"""FastAPI server for the tour operator site.

Storage: JSON files in DATA_DIR.
Auth: JWT for the admin panel.
All API routes are prefixed with /api.

Frontend:
FastAPI serves the React build and injects runtime SEO meta for page URLs.
"""

from __future__ import annotations

from article_content import sync_article_text

import asyncio
import logging
import os
import re
import smtplib
from functools import lru_cache
import uuid
from contextlib import suppress
from copy import deepcopy
from urllib.parse import quote
from datetime import datetime, timezone, date, timedelta, time as datetime_time
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
    UploadFile,
    File,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from auth import (
    ADMIN_COOKIE_MAX_AGE,
    ADMIN_SESSION_COOKIE,
    authenticate,
    clear_login_failures,
    create_access_token,
    decode_token,
    get_current_admin,
    login_retry_after,
    record_login_failure,
    request_client_ip,
    revoke_admin_tokens,
    seed_admin,
    validate_auth_configuration,
)
from homepage import (
    HOME_CONTENT_MIGRATION_TIMESTAMP,
    home_faq_content,
    homepage_settings_changed,
    is_home_faq,
    settings_with_home_defaults,
)
from seed import run_seed
from seo_runtime import (
    FRONTEND_BUILD_DIR,
    build_robots_txt,
    build_sitemap_xml,
    canonical_url_for_path,
    get_http_status_for_path,
    get_redirect_target,
    is_listed_article,
    is_listed_tour,
    is_public_tour,
    render_index_html,
    settings_with_seo_hub_defaults,
    sort_reviews,
    stamp_changed_seo_hubs,
)
from storage import (
    DATA_DIR as STORAGE_DATA_DIR,
    add_item,
    delete_item,
    get_by,
    list_items,
    load,
    save,
    update_item,
)
from tracking import send_server_conversion_events
from tour_program_pdf import build_tour_program_pdf


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("travelspace")


app = FastAPI(title="Tour Operator API")
api = APIRouter(prefix="/api")


class HeadAsGetMiddleware:
    """Serve HEAD through the matching GET route and omit only the body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        get_scope = dict(scope)
        get_scope["method"] = "GET"
        body_finished = False

        async def send_head(message):
            nonlocal body_finished
            if message.get("type") != "http.response.body":
                await send(message)
                return
            if not message.get("more_body", False) and not body_finished:
                body_finished = True
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    }
                )

        await self.app(get_scope, receive, send_head)


class SelectiveGZipMiddleware:
    """Compress HTML, JSON, CSS and JS without recompressing media files."""

    ALREADY_COMPRESSED_SUFFIXES = {
        ".avif",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".mp3",
        ".mp4",
        ".pdf",
        ".png",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".zip",
    }

    def __init__(self, app, minimum_size: int = 1000):
        self.app = app
        self.gzip_app = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        if Path(path).suffix.lower() in self.ALREADY_COMPRESSED_SUFFIXES:
            await self.app(scope, receive, send)
            return
        await self.gzip_app(scope, receive, send)


# All tour-date retention rules use Belarus local time (UTC+3).
BELARUS_TIMEZONE = ZoneInfo("Europe/Minsk")
DEFAULT_AUTO_DELETE_DAYS_BEFORE = 0
MAX_AUTO_DELETE_DAYS_BEFORE = 3650
_tour_date_cleanup_task: asyncio.Task | None = None


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "https://travelspace.by,https://www.travelspace.by,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).strip()
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS must contain explicit site origins; wildcard is forbidden"
        )
    if any(not origin.startswith(("http://", "https://")) for origin in origins):
        raise RuntimeError("Every CORS_ORIGINS entry must be an http(s) origin")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(HeadAsGetMiddleware)
app.add_middleware(SelectiveGZipMiddleware, minimum_size=1000)


def _cookie_secure() -> bool:
    configured = os.environ.get("COOKIE_SECURE")
    if configured is not None:
        normalized = configured.strip().lower()
        if normalized not in {"true", "false"}:
            raise RuntimeError("COOKIE_SECURE must be true or false")
        secure = normalized == "true"
        if (
            not secure
            and os.environ.get("PUBLIC_SITE_URL", "").lower().startswith("https://")
        ):
            raise RuntimeError("COOKIE_SECURE cannot be false for an HTTPS site")
        return secure
    return os.environ.get("PUBLIC_SITE_URL", "").lower().startswith("https://")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    if _cookie_secure():
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    if request.url.path.startswith(("/api/auth", "/api/admin")):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith(("/static/", "/uploads/", "/fonts/")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith("/media/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path in {
        "/background-journey.mp4",
        "/og-image.jpg",
        "/favicon.ico",
        "/favicon.png",
        "/favicon-48x48.png",
        "/apple-touch-icon.png",
        "/manifest.json",
    }:
        response.headers["Cache-Control"] = "public, max-age=604800"
    return response


UPLOAD_DIR = Path(
    os.environ.get("UPLOADS_DIR") or ROOT_DIR / "uploads"
).expanduser().resolve()

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount(
    "/uploads",
    StaticFiles(directory=str(UPLOAD_DIR)),
    name="uploads",
)


# ---------- Models ---------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    user: dict
    csrf_token: str


class LeadIn(BaseModel):
    name: str | None = None
    phone: str
    tour: str | None = None
    tour_slug: str | None = None
    region: str | None = None
    date: str | None = None
    comment: str | None = None
    source_page: str | None = None
    consent: bool = True
    form_type: str = "consultation"  # consultation | tour | agency
    extra: dict | None = None
    event_id: str | None = None
    page_url: str | None = None
    landing_page: str | None = None
    referrer: str | None = None
    utm: dict | None = None
    click_ids: dict | None = None


class LeadStatusIn(BaseModel):
    status: str  # new | in_progress | closed


# ---------- Helpers --------------------------------------------------------


PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,}$")


def _ensure_phone(phone: str) -> str:
    if not phone or not PHONE_RE.match(phone.strip()):
        raise HTTPException(
            status_code=422,
            detail="Введите корректный номер телефона",
        )
    return phone.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(extra: dict | None = None) -> dict:
    return {"ok": True, **(extra or {})}


def _as_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _lead_form_type_label(form_type: str | None) -> str:
    labels = {
        "consultation": "Консультация",
        "tour": "Заявка на тур",
        "agency": "Заявка агентства",
    }
    return labels.get(form_type or "", form_type or "Заявка")


def _lead_email_recipient() -> str | None:
    settings = load("settings", default={})
    return (
        _as_text(settings.get("lead_email"))
        or _as_text(os.environ.get("LEAD_EMAIL"))
        or None
    )


def _lead_email_rows(lead: dict) -> list[tuple[str, str]]:
    extra = lead.get("extra") if isinstance(lead.get("extra"), dict) else {}
    utm = lead.get("utm") if isinstance(lead.get("utm"), dict) else {}
    click_ids = (
        lead.get("click_ids") if isinstance(lead.get("click_ids"), dict) else {}
    )

    rows = [
        ("Тип заявки", _lead_form_type_label(lead.get("form_type"))),
        ("Имя", _as_text(lead.get("name")) or "—"),
        ("Телефон", _as_text(lead.get("phone"))),
        ("Тур", _as_text(lead.get("tour")) or "—"),
        ("Slug тура", _as_text(lead.get("tour_slug")) or "—"),
        ("Регион / направление", _as_text(lead.get("region")) or "—"),
        ("Дата", _as_text(lead.get("date")) or "—"),
        ("Комментарий", _as_text(lead.get("comment")) or "—"),
    ]

    if extra:
        extra_labels = {
            "hotel": "Отель",
            "room": "Номер",
            "meal_plan": "План питания",
            "final_price": "Итоговая стоимость",
            "company": "Компания / агентство",
            "email": "Email клиента",
        }

        for key, label in extra_labels.items():
            if _as_text(extra.get(key)):
                rows.append((label, _as_text(extra.get(key))))

    rows.extend(
        [
            ("Страница / место формы", _as_text(lead.get("source_page")) or "—"),
            ("URL отправки заявки", _as_text(lead.get("page_url")) or "—"),
            ("Первая страница визита", _as_text(lead.get("landing_page")) or "—"),
            (
                "Источник перехода (referrer)",
                _as_text(lead.get("referrer")) or "Прямой переход / не определён",
            ),
            ("UTM source", _as_text(utm.get("utm_source")) or "—"),
            ("UTM medium", _as_text(utm.get("utm_medium")) or "—"),
            ("UTM campaign", _as_text(utm.get("utm_campaign")) or "—"),
            ("UTM term", _as_text(utm.get("utm_term")) or "—"),
            ("UTM content", _as_text(utm.get("utm_content")) or "—"),
        ]
    )

    click_id_labels = {
        "gclid": "Google Click ID (gclid)",
        "yclid": "Яндекс Click ID (yclid)",
        "fbclid": "Meta Click ID (fbclid)",
        "ttclid": "TikTok Click ID (ttclid)",
        "fbp": "Meta Browser ID (fbp)",
        "fbc": "Meta Click Cookie (fbc)",
    }
    for key, label in click_id_labels.items():
        if _as_text(click_ids.get(key)):
            rows.append((label, _as_text(click_ids.get(key))))

    rows.extend(
        [
            ("ID события аналитики", _as_text(lead.get("event_id")) or "—"),
            ("IP", _as_text(lead.get("ip")) or "—"),
            ("Устройство / браузер", _as_text(lead.get("user_agent")) or "—"),
            ("ID заявки", _as_text(lead.get("id"))),
            ("Создана", _as_text(lead.get("created_at"))),
        ]
    )

    return rows


def _build_lead_email(lead: dict, recipient: str) -> EmailMessage:
    settings = load("settings", default={})
    company = _as_text(settings.get("company_short")) or "TRAVELSPACE"

    subject = f"Новая заявка с сайта {company}"
    if _as_text(lead.get("tour")):
        subject += f": {_as_text(lead.get('tour'))}"

    rows = _lead_email_rows(lead)

    text_body = "Новая заявка с сайта\n\n" + "\n".join(
        f"{label}: {value}" for label, value in rows
    )

    html_rows = "".join(
        "<tr>"
        f"<td style='padding:10px 12px;border:1px solid #d1d5db;background:#f9fafb;color:#111827;font-weight:700'>{escape(label)}</td>"
        f"<td style='padding:10px 12px;border:1px solid #d1d5db;background:#ffffff;color:#111827'>{escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )

    html_body = f"""
    <div style="margin:0;padding:16px;background:#ffffff;font-family:Arial,sans-serif;color:#111827;line-height:1.5">
      <h2 style="margin:0 0 16px;color:#111827;font-size:20px;line-height:1.25">Новая заявка с сайта</h2>
      <table style="border-collapse:collapse;width:100%;max-width:760px;background:#ffffff;color:#111827;font-size:14px">
        {html_rows}
      </table>
    </div>
    """

    from_email = (
        _as_text(os.environ.get("SMTP_FROM_EMAIL"))
        or _as_text(os.environ.get("SMTP_FROM"))
        or _as_text(os.environ.get("SMTP_USER"))
        or f"no-reply@{os.environ.get('SMTP_FROM_DOMAIN', 'travelspace.by')}"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = recipient
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _send_lead_email(lead: dict) -> None:
    recipient = _lead_email_recipient()

    if not recipient:
        logger.warning("Lead email skipped: settings.lead_email is empty")
        return

    smtp_host = _as_text(os.environ.get("SMTP_HOST"))
    smtp_user = _as_text(os.environ.get("SMTP_USER"))
    smtp_password = _as_text(os.environ.get("SMTP_PASSWORD"))
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

    if not smtp_host:
        logger.warning(
            "Lead email skipped: SMTP_HOST is not configured. Recipient would be %s",
            recipient,
        )
        return

    msg = _build_lead_email(lead, recipient)

    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                if smtp_use_tls:
                    server.starttls()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)

        logger.info(
            "Lead email sent: lead_id=%s recipient=%s",
            lead.get("id"),
            recipient,
        )

    except Exception:
        logger.exception(
            "Lead email sending failed: lead_id=%s recipient=%s",
            lead.get("id"),
            recipient,
        )


def _order_value(item: dict) -> int:
    try:
        return int(item.get("order") or 0)
    except (TypeError, ValueError):
        return 0


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _belarus_today() -> date:
    return datetime.now(BELARUS_TIMEZONE).date()


def _tour_auto_delete_days_before(tour: dict | None) -> int:
    if not isinstance(tour, dict):
        return DEFAULT_AUTO_DELETE_DAYS_BEFORE

    raw_value = tour.get(
        "auto_delete_dates_days_before",
        DEFAULT_AUTO_DELETE_DAYS_BEFORE,
    )

    try:
        days_before = int(raw_value)
    except (TypeError, ValueError):
        days_before = DEFAULT_AUTO_DELETE_DAYS_BEFORE

    return max(0, min(days_before, MAX_AUTO_DELETE_DAYS_BEFORE))


def _tour_dates(tour: dict) -> list[dict]:
    dates = list(tour.get("dates") or [])

    for chain in tour.get("chains") or []:
        dates.extend(chain.get("dates") or [])

    return dates


def _date_ref_values(item: dict | None) -> set[str]:
    if not isinstance(item, dict):
        return set()

    values = {
        _as_text(item.get("id")),
        _as_text(item.get("start")),
        _as_text(item.get("date_id")),
        _as_text(item.get("date_start")),
        _as_text(item.get("date_label")),
    }

    if _as_text(item.get("start")) and _as_text(item.get("end")):
        values.add(f"{_as_text(item.get('start'))} → {_as_text(item.get('end'))}")

    return {value for value in values if value}


def _is_departure_date_actual(
    item: dict | None,
    today: date | None = None,
    days_before: int = DEFAULT_AUTO_DELETE_DAYS_BEFORE,
) -> bool:
    """Return True when a departure date can still be shown for booking.

    A date is removed at 00:00 Belarus time on
    ``start date - auto_delete_dates_days_before``. For example, a 30 July
    departure with a five-day setting is removed on 25 July at 00:00.
    """

    if today is None:
        today = _belarus_today()

    if not isinstance(item, dict):
        return True

    days_before = max(0, int(days_before or 0))

    start = _parse_date(_as_text(item.get("start") or item.get("date_start")))
    if start:
        return today < start - timedelta(days=days_before)

    end = _parse_date(_as_text(item.get("end")))
    if end:
        return today < end - timedelta(days=days_before)

    return True


def _clean_stale_room_date_links(
    rooms: list,
    removed_refs: set[str],
    today: date,
    days_before: int,
) -> bool:
    changed = False

    for room in rooms or []:
        if not isinstance(room, dict):
            continue

        date_prices = room.get("date_prices")
        if isinstance(date_prices, list):
            next_prices = []

            for price in date_prices:
                refs = _date_ref_values(price if isinstance(price, dict) else {})
                if refs & removed_refs:
                    changed = True
                    continue

                if isinstance(price, dict) and not _is_departure_date_actual(
                    price,
                    today,
                    days_before,
                ):
                    changed = True
                    continue

                next_prices.append(price)

            if len(next_prices) != len(date_prices):
                room["date_prices"] = next_prices
                changed = True

        unavailable_dates = room.get("unavailable_dates")
        if isinstance(unavailable_dates, list):
            next_unavailable = [
                value
                for value in unavailable_dates
                if _as_text(value) not in removed_refs
            ]

            if len(next_unavailable) != len(unavailable_dates):
                room["unavailable_dates"] = next_unavailable
                changed = True

    return changed


def _clean_stale_hotel_date_links(
    hotels: list,
    removed_refs: set[str],
    today: date,
    days_before: int,
) -> bool:
    changed = False

    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            continue

        rooms = hotel.get("rooms")
        if isinstance(rooms, list):
            changed = _clean_stale_room_date_links(
                rooms,
                removed_refs,
                today,
                days_before,
            ) or changed

    return changed


def _prune_tour_departure_dates(tour: dict, today: date | None = None) -> bool:
    if today is None:
        today = _belarus_today()

    changed = False
    days_before = _tour_auto_delete_days_before(tour)

    def prune_dates(dates: list | None) -> tuple[list, set[str]]:
        nonlocal changed

        if not isinstance(dates, list):
            return [], set()

        next_dates = []
        removed_refs: set[str] = set()

        for item in dates:
            if isinstance(item, dict) and not _is_departure_date_actual(
                item,
                today,
                days_before,
            ):
                removed_refs.update(_date_ref_values(item))
                changed = True
                continue

            next_dates.append(item)

        return next_dates, removed_refs

    if isinstance(tour.get("dates"), list):
        next_dates, removed_refs = prune_dates(tour.get("dates"))
        if len(next_dates) != len(tour.get("dates") or []):
            tour["dates"] = next_dates
        if removed_refs:
            changed = _clean_stale_hotel_date_links(
                tour.get("hotels") if isinstance(tour.get("hotels"), list) else [],
                removed_refs,
                today,
                days_before,
            ) or changed

    chains = tour.get("chains")
    if isinstance(chains, list):
        for chain in chains:
            if not isinstance(chain, dict):
                continue

            next_dates, removed_refs = prune_dates(chain.get("dates"))
            if isinstance(chain.get("dates"), list) and len(next_dates) != len(chain.get("dates") or []):
                chain["dates"] = next_dates

            if removed_refs:
                changed = _clean_stale_hotel_date_links(
                    chain.get("hotels") if isinstance(chain.get("hotels"), list) else [],
                    removed_refs,
                    today,
                    days_before,
                ) or changed

    return changed


def _prune_all_tour_departure_dates() -> list[dict]:
    tours = list_items("tours")
    today = _belarus_today()
    changed = False

    for tour in tours:
        if isinstance(tour, dict):
            changed = _prune_tour_departure_dates(tour, today) or changed

    if changed:
        save("tours", tours)
        logger.info("Stale tour departure dates were pruned")

    return tours


def _seconds_until_next_belarus_midnight() -> float:
    now = datetime.now(BELARUS_TIMEZONE)
    next_day = now.date() + timedelta(days=1)
    next_midnight = datetime.combine(
        next_day,
        datetime_time.min,
        tzinfo=BELARUS_TIMEZONE,
    )

    return max(1.0, (next_midnight - now).total_seconds())


async def _run_tour_date_cleanup_daily() -> None:
    while True:
        await asyncio.sleep(_seconds_until_next_belarus_midnight())

        try:
            _prune_all_tour_departure_dates()
            logger.info("Scheduled tour date cleanup completed (Europe/Minsk).")
        except Exception:
            logger.exception("Scheduled tour date cleanup failed")


def _is_tour_expired(tour: dict) -> bool:
    start_dates = [
        parsed
        for parsed in (_parse_date(d.get("start")) for d in _tour_dates(tour))
        if parsed
    ]

    if not start_dates:
        return False

    return not any(start_date >= _belarus_today() for start_date in start_dates)


def _safe_frontend_file(full_path: str) -> FileResponse | None:
    """
    Serve real files from React build root if they exist.

    This is useful for root public files from CRA build:
    /favicon.ico
    /manifest.json
    /asset-manifest.json
    /background-journey.mp4
    /og-image.jpg
    etc.
    """
    if not full_path:
        return None

    build_root = FRONTEND_BUILD_DIR.resolve()
    requested_file = (build_root / full_path).resolve()

    if not str(requested_file).startswith(str(build_root)):
        return None

    if not requested_file.is_file():
        return None

    return FileResponse(str(requested_file))



# ---------- Compact PDF programs ------------------------------------------


TOUR_PDF_PROGRAMS_COLLECTION = "tour_pdf_programs"


def _default_tour_pdf_program(
    tour: dict,
    settings: dict | None = None,
) -> dict:
    """Build the downloadable program directly from the current tour data."""
    settings = settings or {}
    days = []

    for index, day in enumerate(tour.get("program") or [], start=1):
        if not isinstance(day, dict):
            continue

        days.append(
            {
                "id": _as_text(day.get("id")) or str(uuid.uuid4()),
                "day": _as_text(day.get("day")) or str(index),
                "title": _as_text(day.get("title")) or f"День {index}",
                "description": _as_text(
                    day.get("description") or day.get("notes")
                ),
            }
        )

    return {
        "header_company": _as_text(
            settings.get("company_short")
            or settings.get("company_name")
            or "TRAVELSPACE"
        ),
        "header_title": _as_text(tour.get("title")) or "Программа тура",
        "intro": _as_text(
            tour.get("tagline")
            or tour.get("short_description")
            or tour.get("description")
        ),
        "days": days,
        "included": [
            _as_text(item)
            for item in (tour.get("included") or [])
            if _as_text(item)
        ],
        "excluded": [
            _as_text(item)
            for item in (tour.get("excluded") or [])
            if _as_text(item)
        ],
        "important_info": [
            _as_text(item)
            for item in (tour.get("important_info") or [])
            if _as_text(item)
        ],
        "show_info_blocks": True,
        "footer_company": _as_text(
            settings.get("company_short")
            or settings.get("company_name")
            or "TRAVELSPACE"
        ),
        "footer_site": _as_text(settings.get("site_url") or "travelspace.by"),
        "footer_phone": _as_text(
            settings.get("phone")
            or settings.get("company_phone")
            or "+375 29 636 99 11"
        ),
        "source": "tour_program",
    }


def _normalize_tour_pdf_program(
    payload: dict,
    tour: dict,
    settings: dict | None = None,
) -> dict:
    fallback = _default_tour_pdf_program(tour, settings)
    raw_days = payload.get("days") if isinstance(payload.get("days"), list) else []
    raw_days = [
        day
        for day in raw_days
        if isinstance(day, dict)
        and (
            _as_text(day.get("title"))
            or _as_text(day.get("description") or day.get("text"))
        )
    ]
    days = []

    for index, day in enumerate(raw_days, start=1):
        if not isinstance(day, dict):
            continue

        title = _as_text(day.get("title"))
        description = _as_text(day.get("description") or day.get("text"))
        day_number = _as_text(day.get("day")) or str(index)

        if not title and not description:
            continue

        days.append(
            {
                "id": _as_text(day.get("id")) or str(uuid.uuid4()),
                "day": day_number,
                "title": title or f"День {day_number}",
                "description": description,
            }
        )

    def _strings(key: str) -> list[str]:
        value = payload.get(key)

        if not isinstance(value, list):
            return fallback[key]

        return [_as_text(item) for item in value if _as_text(item)]

    def _editable_text(key: str) -> str:
        if key not in payload:
            return fallback[key]
        return _as_text(payload.get(key))

    return {
        "header_company": _editable_text("header_company"),
        "header_title": _editable_text("header_title"),
        "intro": _as_text(payload.get("intro")),
        "days": days,
        "included": _strings("included"),
        "excluded": _strings("excluded"),
        "important_info": _strings("important_info"),
        "show_info_blocks": payload.get("show_info_blocks") is not False,
        "footer_company": _editable_text("footer_company"),
        "footer_site": _editable_text("footer_site"),
        "footer_phone": _editable_text("footer_phone"),
        "source": "admin",
    }


def _tour_pdf_program_record(tour_id: str | None) -> dict | None:
    if not tour_id:
        return None

    return next(
        (
            item
            for item in list_items(TOUR_PDF_PROGRAMS_COLLECTION)
            if item.get("tour_id") == tour_id
        ),
        None,
    )


def _saved_tour_pdf_program(
    tour_id: str | None,
    tour: dict | None = None,
    settings: dict | None = None,
) -> dict | None:
    record = _tour_pdf_program_record(tour_id)
    if not record:
        return None

    fallback = _default_tour_pdf_program(tour or {}, settings)

    def _saved_text(key: str) -> str:
        return _as_text(record.get(key)) if key in record else fallback[key]

    return {
        "header_company": _saved_text("header_company"),
        "header_title": _saved_text("header_title"),
        "intro": record.get("intro") or "",
        "days": record.get("days") if isinstance(record.get("days"), list) else [],
        "included": (
            record.get("included")
            if isinstance(record.get("included"), list)
            else []
        ),
        "excluded": (
            record.get("excluded")
            if isinstance(record.get("excluded"), list)
            else []
        ),
        "important_info": (
            record.get("important_info")
            if isinstance(record.get("important_info"), list)
            else []
        ),
        "show_info_blocks": record.get("show_info_blocks") is not False,
        "footer_company": _saved_text("footer_company"),
        "footer_site": _saved_text("footer_site"),
        "footer_phone": _saved_text("footer_phone"),
        "source": "admin",
    }


# ---------- Public endpoints ----------------------------------------------


@api.get("/")
async def root():
    return {"name": "Tour Operator API", "status": "ok"}


@api.get("/settings")
async def get_settings():
    data = load("settings", default={})
    return settings_with_seo_hub_defaults(settings_with_home_defaults(data))


@api.get("/tours")
async def get_tours(region: str | None = None, badge: str | None = None):
    # Public reads also clean stale departure dates from JSON storage.
    # A past date inside a chain is deleted, but the tour itself remains.
    items = [t for t in _prune_all_tour_departure_dates() if is_listed_tour(t)]

    if region:
        items = [t for t in items if t.get("region_slug") == region]

    if badge:
        items = [t for t in items if badge in (t.get("badges") or [])]

    items.sort(key=_order_value)
    return items


@api.get("/tours/{slug}")
async def get_tour(slug: str):
    tours = _prune_all_tour_departure_dates()
    tour = next((t for t in tours if t.get("slug") == slug), None)

    if not is_public_tour(tour):
        raise HTTPException(status_code=404, detail="Тур не найден")

    return tour


@api.get("/tours/{slug}/program.pdf")
async def download_tour_program(slug: str):
    tours = _prune_all_tour_departure_dates()
    tour = next((t for t in tours if t.get("slug") == slug), None)

    if not is_public_tour(tour):
        raise HTTPException(status_code=404, detail="Тур не найден")

    try:
        settings = load("settings", default={})
        program_config = _default_tour_pdf_program(tour, settings)
        pdf = build_tour_program_pdf(
            tour,
            settings=settings,
            upload_dir=UPLOAD_DIR,
            program_config=program_config,
        )
    except Exception:
        logger.exception("Tour program PDF generation failed: slug=%s", slug)
        raise HTTPException(status_code=500, detail="Не удалось сформировать PDF")

    filename = f"tour-program-{slug}.pdf"

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{filename}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@api.get("/reviews")
async def get_reviews():
    items = [r for r in list_items("reviews") if r.get("active", True)]
    return sort_reviews(items)


@api.get("/articles")
async def get_articles():
    items = [a for a in list_items("articles") if is_listed_article(a)]
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items


@api.get("/articles/{slug}")
async def get_article(slug: str):
    article = get_by("articles", "slug", slug)

    if not article or not article.get("active", True):
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return article


@api.get("/faq")
async def get_faq():
    items = [f for f in list_items("faq") if f.get("active", True)]
    items.sort(key=_order_value)
    return items


@api.get("/promotions")
async def get_promotions():
    items = [p for p in list_items("promotions") if p.get("active", True)]
    return items


@api.post("/leads")
async def create_lead(
    payload: LeadIn,
    request: Request,
    background_tasks: BackgroundTasks,
):
    phone = _ensure_phone(payload.phone)

    if not payload.consent:
        raise HTTPException(
            status_code=422,
            detail="Необходимо согласие на обработку персональных данных",
        )

    lead = payload.model_dump()
    lead["phone"] = phone
    lead["id"] = str(uuid.uuid4())
    lead["status"] = "new"
    lead["created_at"] = _now()

    forwarded_for = request.headers.get("x-forwarded-for")
    lead["ip"] = (
        forwarded_for.split(",", 1)[0].strip()
        if forwarded_for
        else request.client.host if request.client else None
    )
    lead["user_agent"] = request.headers.get("user-agent")
    lead["page_url"] = lead.get("page_url") or request.headers.get("referer")

    click_ids = lead.get("click_ids") if isinstance(lead.get("click_ids"), dict) else {}
    if request.cookies.get("_fbp") and not click_ids.get("fbp"):
        click_ids["fbp"] = request.cookies.get("_fbp")
    if request.cookies.get("_fbc") and not click_ids.get("fbc"):
        click_ids["fbc"] = request.cookies.get("_fbc")
    lead["click_ids"] = click_ids

    add_item("leads", lead)

    background_tasks.add_task(_send_lead_email, lead)
    background_tasks.add_task(send_server_conversion_events, lead)

    logger.info(
        "New lead saved: id=%s phone=%s tour=%s",
        lead["id"],
        phone,
        payload.tour_slug,
    )

    return _ok({"id": lead["id"]})


# ---------- Auth -----------------------------------------------------------


@api.post("/auth/login", response_model=LoginOut)
async def login(payload: LoginIn, request: Request, response: Response):
    client_ip = request_client_ip(request)
    retry_after = login_retry_after(client_ip, payload.email)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Попробуйте позже.",
            headers={"Retry-After": str(retry_after)},
        )

    user = authenticate(payload.email, payload.password)

    if not user:
        record_login_failure(client_ip, payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    clear_login_failures(client_ip, payload.email)
    token, csrf_token, lifetime_seconds = create_access_token(user)
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        max_age=lifetime_seconds,
        expires=lifetime_seconds,
        path="/api",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )
    return {
        "user": {
            "email": user["email"],
            "name": user.get("name") or "Administrator",
            "role": "admin",
        },
        "csrf_token": csrf_token,
    }


@api.get("/auth/me")
async def me(request: Request, response: Response, current=Depends(get_current_admin)):
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    payload = decode_token(token)
    if payload.get("persistent") is True and "exp" not in payload:
        response.set_cookie(
            key=ADMIN_SESSION_COOKIE,
            value=token,
            max_age=ADMIN_COOKIE_MAX_AGE,
            expires=ADMIN_COOKIE_MAX_AGE,
            path="/api",
            secure=_cookie_secure(),
            httponly=True,
            samesite="strict",
        )
    return current


@api.post("/auth/logout")
async def logout(response: Response, current=Depends(get_current_admin)):
    revoke_admin_tokens(current["email"])
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/api",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )
    return _ok()


@api.post("/admin/upload")
async def admin_upload_file(
    file: UploadFile = File(...),
    current=Depends(get_current_admin),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Можно загружать только изображения",
        )

    content = await file.read(2 * 1024 * 1024 + 1)

    # 2 MB лимит уже после сжатия на фронте
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    from io import BytesIO
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(content)) as image:
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}.get(image.format)
            if not ext:
                raise ValueError("Unsupported image format")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Не удалось прочитать изображение. Используйте JPG, PNG или WebP.")

    filename = f"{uuid.uuid4()}{ext}"
    path = UPLOAD_DIR / filename
    path.write_bytes(content)

    return {"url": f"/uploads/{filename}"}


# ---------- Admin CRUD -----------------------------------------------------


def _make_unique_slug(base_slug: str, existing_slugs: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9-]+", "-", _as_text(base_slug).lower()).strip("-")
    base = re.sub(r"-+", "-", base) or "tour-copy"

    candidate = base
    index = 2

    while candidate in existing_slugs:
        candidate = f"{base}-{index}"
        index += 1

    return candidate



@api.get("/admin/tours/{item_id}/pdf-program")
async def admin_get_tour_pdf_program(
    item_id: str,
    current=Depends(get_current_admin),
):
    tour = next(
        (item for item in list_items("tours") if item.get("id") == item_id),
        None,
    )

    if not tour:
        raise HTTPException(status_code=404, detail="Тур не найден")

    settings = load("settings", default={})
    generated_program = _default_tour_pdf_program(tour, settings)

    return {
        "tour_id": tour.get("id"),
        "title": tour.get("title"),
        "slug": tour.get("slug"),
        "pdf_program": generated_program,
        "source_program": generated_program,
        "is_generated": True,
        "automatic": True,
        "summary": {
            "days": len(generated_program.get("days") or []),
            "included": len(generated_program.get("included") or []),
            "excluded": len(generated_program.get("excluded") or []),
            "important_info": len(generated_program.get("important_info") or []),
            "faq": len(tour.get("faq") or []),
        },
    }


@api.put("/admin/tours/{item_id}/pdf-program")
async def admin_update_tour_pdf_program(
    item_id: str,
    payload: dict,
    current=Depends(get_current_admin),
):
    tour = next(
        (item for item in list_items("tours") if item.get("id") == item_id),
        None,
    )

    if not tour:
        raise HTTPException(status_code=404, detail="Тур не найден")

    settings = load("settings", default={})
    pdf_program = _default_tour_pdf_program(tour, settings)

    return {
        "ok": True,
        "automatic": True,
        "message": "PDF формируется автоматически из карточки тура.",
        "pdf_program": pdf_program,
        "record_id": None,
    }


def _duplicate_tour(item_id: str) -> dict:
    tours = list_items("tours")
    source = next((tour for tour in tours if tour.get("id") == item_id), None)

    if not source:
        raise HTTPException(status_code=404, detail="Тур не найден")

    existing_slugs = {str(tour.get("slug") or "") for tour in tours}
    base_slug = f"{source.get('slug') or 'tour'}-copy"

    item = deepcopy(source)
    item["id"] = str(uuid.uuid4())
    item["title"] = f"{_as_text(source.get('title')) or 'Тур'} (копия)"
    item["slug"] = _make_unique_slug(base_slug, existing_slugs)
    item["active"] = False
    item["hidden"] = True
    item["order"] = _order_value(source) + 1
    item["created_at"] = _now()
    item["updated_at"] = _now()
    item["seo_lastmod"] = ""

    add_item("tours", item)
    return item


CONTENT_COLLECTIONS = {"tours", "articles"}
SEO_CONTENT_MIGRATION_TIMESTAMP = "2026-08-20T00:00:00+03:00"
SEO_H1_MIGRATIONS = {
    "avtobusniy-tur-v-peterburg-na-vyhodnye": (
        "Автобусный тур в Санкт-Петербург из Минска на выходные"
    ),
}
CONTENT_TIMESTAMP_EXCLUDED_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "content_updated_at",
    "seo_lastmod",
    "active",
    "hidden",
    "hide_from_catalog",
    "order",
    "auto_delete_dates_days_before",
}


def _content_changed(existing: dict, payload: dict) -> bool:
    keys = set(payload) - CONTENT_TIMESTAMP_EXCLUDED_KEYS
    return any(existing.get(key) != payload.get(key) for key in keys)


def _normalize_content_seo(name: str, item: dict, existing: dict | None = None) -> None:
    if name == "articles":
        try:
            sync_article_text(item)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    if name not in CONTENT_COLLECTIONS:
        return
    slug = item.get("slug") or (existing or {}).get("slug")
    canonical = item.get("seo_canonical_url")
    if not slug or not canonical:
        return
    prefix = "/tours/" if name == "tours" else "/blog/"
    item["seo_canonical_url"] = canonical_url_for_path(canonical, prefix + str(slug))


def _backfill_content_timestamps() -> None:
    """Give legacy public content one truthful, stable SEO migration date.

    The server-rendered body is a substantive change to every legacy tour and
    article. The fixed release timestamp is written only when updated_at is
    missing, so Passenger restarts never manufacture a fresh sitemap date.
    """

    for collection in CONTENT_COLLECTIONS:
        items = list_items(collection)
        changed = False
        for item in items:
            if not item.get("updated_at"):
                item["updated_at"] = SEO_CONTENT_MIGRATION_TIMESTAMP
                changed = True
            if collection == "tours" and not item.get("seo_h1"):
                migrated_h1 = SEO_H1_MIGRATIONS.get(str(item.get("slug") or ""))
                if migrated_h1:
                    item["seo_h1"] = migrated_h1
                    changed = True
        if changed:
            save(collection, items)


def _touch_home_content_timestamp(value: str | None = None) -> str:
    settings = load("settings", default={})
    settings = dict(settings) if isinstance(settings, dict) else {}
    timestamp = value or _now()
    settings["home_content_updated_at"] = timestamp
    save("settings", settings)
    return timestamp


def _backfill_home_content_timestamp() -> None:
    """Record this homepage SEO release once without changing it on restart."""

    settings = load("settings", default={})
    settings = dict(settings) if isinstance(settings, dict) else {}
    if settings.get("home_content_updated_at"):
        return
    _touch_home_content_timestamp(HOME_CONTENT_MIGRATION_TIMESTAMP)


def _crud_create(name: str, payload: dict) -> dict:
    item = {**payload, "id": str(uuid.uuid4())}
    _normalize_content_seo(name, item)

    if "active" not in item:
        item["active"] = True

    if name == "tours":
        _prune_tour_departure_dates(item)

    if name in CONTENT_COLLECTIONS:
        now = _now()
        item["created_at"] = now
        item["updated_at"] = now

    add_item(name, item)
    if name == "faq" and is_home_faq(item):
        _touch_home_content_timestamp()
    return item


def _crud_update(name: str, item_id: str, payload: dict) -> dict:
    payload = {**payload}
    existing = get_by(name, "id", item_id)
    _normalize_content_seo(name, payload, existing)

    if name == "tours":
        _prune_tour_departure_dates(payload)

    if name in CONTENT_COLLECTIONS and existing:
        if _content_changed(existing, payload):
            payload["updated_at"] = _now()
        else:
            payload.pop("updated_at", None)
        payload.pop("created_at", None)

    updated = update_item(name, item_id, payload)

    if not updated:
        raise HTTPException(status_code=404, detail="Не найдено")

    if name == "faq" and home_faq_content(existing) != home_faq_content(updated):
        _touch_home_content_timestamp()

    return updated


def _crud_delete(name: str, item_id: str) -> dict:
    existing = get_by(name, "id", item_id)
    ok = delete_item(name, item_id)

    if not ok:
        raise HTTPException(status_code=404, detail="Не найдено")

    if name == "tours":
        program = _tour_pdf_program_record(item_id)
        if program:
            delete_item(TOUR_PDF_PROGRAMS_COLLECTION, program.get("id"))

    if name == "faq" and is_home_faq(existing):
        _touch_home_content_timestamp()

    return _ok()


COLLECTIONS = [
    "tours",
    "reviews",
    "articles",
    "faq",
    "promotions",
]


@api.get("/admin/settings")
async def admin_get_settings(current=Depends(get_current_admin)):
    return settings_with_seo_hub_defaults(
        settings_with_home_defaults(load("settings", default={}))
    )


@api.put("/admin/settings")
async def admin_update_settings(payload: dict, current=Depends(get_current_admin)):
    existing = load("settings", default={})
    existing = existing if isinstance(existing, dict) else {}
    updated = dict(payload)
    now = _now()
    if homepage_settings_changed(existing, updated):
        updated["home_content_updated_at"] = now
    elif existing.get("home_content_updated_at"):
        updated["home_content_updated_at"] = existing["home_content_updated_at"]
    else:
        updated.pop("home_content_updated_at", None)
    updated = stamp_changed_seo_hubs(existing, updated, now)
    save("settings", updated)
    return _ok()


@api.get("/admin/leads/list")
async def admin_leads_list(current=Depends(get_current_admin)):
    leads = list_items("leads")
    leads.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return leads


@api.patch("/admin/leads/{item_id}")
async def admin_leads_update(
    item_id: str,
    payload: LeadStatusIn,
    current=Depends(get_current_admin),
):
    return _crud_update("leads", item_id, {"status": payload.status})


@api.delete("/admin/leads/{item_id}")
async def admin_leads_delete(item_id: str, current=Depends(get_current_admin)):
    return _crud_delete("leads", item_id)


@api.post("/admin/tours/{item_id}/duplicate")
async def admin_duplicate_tour(
    item_id: str,
    current=Depends(get_current_admin),
):
    return _duplicate_tour(item_id)


@api.get("/admin/{collection}")
async def admin_list(collection: str, current=Depends(get_current_admin)):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")

    if collection == "tours":
        return _prune_all_tour_departure_dates()

    return list_items(collection)


@api.post("/admin/{collection}")
async def admin_create(
    collection: str,
    payload: dict,
    current=Depends(get_current_admin),
):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")

    return _crud_create(collection, payload)


@api.put("/admin/{collection}/{item_id}")
async def admin_update(
    collection: str,
    item_id: str,
    payload: dict,
    current=Depends(get_current_admin),
):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")

    return _crud_update(collection, item_id, payload)


@api.delete("/admin/{collection}/{item_id}")
async def admin_delete(
    collection: str,
    item_id: str,
    current=Depends(get_current_admin),
):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")

    return _crud_delete(collection, item_id)


# ---------- Mount router ---------------------------------------------------


app.include_router(api)


# ---------- Frontend runtime SEO, sitemap & robots -------------------------


def _frontend_file_response(filename: str):
    file_response = _safe_frontend_file(filename)

    if not file_response:
        raise HTTPException(status_code=404, detail="File not found")

    return file_response


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    return Response(content=build_sitemap_xml(), media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return PlainTextResponse(build_robots_txt())


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return _frontend_file_response("favicon.ico")


@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return _frontend_file_response("manifest.json")


@app.get("/asset-manifest.json", include_in_schema=False)
async def asset_manifest():
    return _frontend_file_response("asset-manifest.json")


@app.get("/og-image.jpg", include_in_schema=False)
async def default_og_image():
    return _frontend_file_response("og-image.jpg")


@app.get("/background-journey.mp4", include_in_schema=False)
async def background_journey_video():
    return _frontend_file_response("background-journey.mp4")


@app.get("/media/{filename}", include_in_schema=False)
def optimized_media(filename: str, width: int = 800):
    """Serve a cached, resized WebP variant of an immutable uploaded image."""
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="File not found")

    source = (UPLOAD_DIR / filename).resolve()
    if not str(source).startswith(str(UPLOAD_DIR)) or not source.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    width = min(1600, max(160, width))
    cache_dir = UPLOAD_DIR / ".optimized"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"{source.stem}-{width}.webp"

    if not cache_file.is_file() or cache_file.stat().st_mtime < source.stat().st_mtime:
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError

            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened)
                if image.width > width:
                    target_height = max(1, round(image.height * width / image.width))
                    image = image.resize((width, target_height), Image.Resampling.LANCZOS)
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGB")
                image.save(cache_file, "WEBP", quality=78, method=4)
        except (UnidentifiedImageError, OSError, ValueError):
            raise HTTPException(status_code=404, detail="Image not available")

    return FileResponse(str(cache_file), media_type="image/webp")


@app.get("/static/{file_path:path}", include_in_schema=False)
async def serve_react_static(file_path: str):
    static_root = (FRONTEND_BUILD_DIR / "static").resolve()
    requested_file = (static_root / file_path).resolve()

    if not str(requested_file).startswith(str(static_root)):
        raise HTTPException(status_code=404, detail="File not found")

    if not requested_file.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(requested_file))


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_react_app(full_path: str):
    if full_path and full_path.endswith("/"):
        return RedirectResponse("/" + full_path.strip("/"), status_code=301)

    path = "/" + full_path.strip("/")

    if path.startswith("/api"):
        raise HTTPException(status_code=404, detail="API route not found")

    public_file = _safe_frontend_file(full_path)
    if public_file:
        return public_file

    redirect_to = get_redirect_target(path)
    if redirect_to:
        return RedirectResponse(redirect_to, status_code=301)

    html, status_code = _cached_public_page(path, _public_page_signature())

    if not html:
        raise HTTPException(
            status_code=404,
            detail=(
                "React build not found. Run `npm run build` in frontend and set "
                "FRONTEND_BUILD_DIR if build is not at ../frontend/build."
            ),
        )

    return HTMLResponse(html, status_code=status_code)


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return 0, 0


def _public_page_signature() -> tuple:
    """Change the cache key whenever public data or the frontend build changes."""
    data_files = tuple(
        (path.name, *_file_signature(path))
        for path in sorted(STORAGE_DATA_DIR.glob("*.json"))
    )
    return (
        _file_signature(FRONTEND_BUILD_DIR / "index.html"),
        _file_signature(FRONTEND_BUILD_DIR / "asset-manifest.json"),
        data_files,
    )


@lru_cache(maxsize=128)
def _cached_public_page(path: str, signature: tuple) -> tuple[str, int]:
    # The signature is deliberately part of the key; the value itself is only
    # needed to invalidate entries after an admin save or a frontend deploy.
    del signature
    return render_index_html(path), get_http_status_for_path(path)


# ---------- Startup --------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    global _tour_date_cleanup_task

    _cookie_secure()
    validate_auth_configuration()
    seed_admin()
    run_seed()
    _backfill_content_timestamps()
    _backfill_home_content_timestamp()
    _prune_all_tour_departure_dates()

    if _tour_date_cleanup_task is None or _tour_date_cleanup_task.done():
        _tour_date_cleanup_task = asyncio.create_task(
            _run_tour_date_cleanup_daily(),
            name="tour-date-cleanup",
        )

    logger.info("Tour operator API started.")
    logger.info("Tour date cleanup timezone: Europe/Minsk (UTC+3)")
    logger.info("Data dir: %s", str(STORAGE_DATA_DIR))
    logger.info("Uploads dir: %s", str(UPLOAD_DIR))
    logger.info("Frontend build dir: %s", str(FRONTEND_BUILD_DIR))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _tour_date_cleanup_task

    if _tour_date_cleanup_task is None:
        return

    _tour_date_cleanup_task.cancel()

    with suppress(asyncio.CancelledError):
        await _tour_date_cleanup_task

    _tour_date_cleanup_task = None
