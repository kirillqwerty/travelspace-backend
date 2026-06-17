"""FastAPI server for the tour operator site.

Storage: JSON files in DATA_DIR.
Auth: JWT for the admin panel.
All API routes are prefixed with /api.

Frontend:
FastAPI serves the React build and injects runtime SEO meta for page URLs.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import uuid
from datetime import datetime, timezone, date, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path

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
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from auth import authenticate, create_access_token, get_current_admin, seed_admin
from seed import run_seed
from seo_runtime import (
    FRONTEND_BUILD_DIR,
    build_robots_txt,
    build_sitemap_xml,
    get_redirect_target,
    render_index_html,
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("travelspace")


app = FastAPI(title="Tour Operator API")
api = APIRouter(prefix="/api")


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "*").strip()

    if raw == "*":
        return ["*"]

    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    token: str
    user: dict


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

    rows = [
        ("Тип заявки", _lead_form_type_label(lead.get("form_type"))),
        ("Имя", _as_text(lead.get("name")) or "—"),
        ("Телефон", _as_text(lead.get("phone"))),
        ("Тур", _as_text(lead.get("tour")) or "—"),
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


def _is_departure_date_actual(item: dict | None, today: date | None = None) -> bool:
    """Return True when a departure date can still be shown for booking.

    We use the departure start date, not the end date: once the tour has
    already departed, that specific departure must disappear, but the tour
    itself must stay active if it has other future dates.
    """

    if today is None:
        today = date.today()

    if not isinstance(item, dict):
        return True

    start = _parse_date(_as_text(item.get("start") or item.get("date_start")))
    if start:
        return start >= today

    end = _parse_date(_as_text(item.get("end")))
    if end:
        return end >= today

    return True


def _clean_stale_room_date_links(rooms: list, removed_refs: set[str], today: date) -> bool:
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

                if isinstance(price, dict) and not _is_departure_date_actual(price, today):
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


def _clean_stale_hotel_date_links(hotels: list, removed_refs: set[str], today: date) -> bool:
    changed = False

    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            continue

        rooms = hotel.get("rooms")
        if isinstance(rooms, list):
            changed = _clean_stale_room_date_links(rooms, removed_refs, today) or changed

    return changed


def _prune_tour_departure_dates(tour: dict, today: date | None = None) -> bool:
    if today is None:
        today = date.today()

    changed = False

    def prune_dates(dates: list | None) -> tuple[list, set[str]]:
        nonlocal changed

        if not isinstance(dates, list):
            return [], set()

        next_dates = []
        removed_refs: set[str] = set()

        for item in dates:
            if isinstance(item, dict) and not _is_departure_date_actual(item, today):
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
                ) or changed

    return changed


def _prune_all_tour_departure_dates() -> list[dict]:
    tours = list_items("tours")
    today = date.today()
    changed = False

    for tour in tours:
        if isinstance(tour, dict):
            changed = _prune_tour_departure_dates(tour, today) or changed

    if changed:
        save("tours", tours)
        logger.info("Stale tour departure dates were pruned")

    return tours


def _is_tour_expired(tour: dict) -> bool:
    start_dates = [
        parsed
        for parsed in (_parse_date(d.get("start")) for d in _tour_dates(tour))
        if parsed
    ]

    if not start_dates:
        return False

    return not any(start_date >= date.today() for start_date in start_dates)


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


# ---------- Public endpoints ----------------------------------------------


@api.get("/")
async def root():
    return {"name": "Tour Operator API", "status": "ok"}


@api.get("/settings")
async def get_settings():
    data = load("settings", default={})
    return data


@api.get("/tours")
async def get_tours(region: str | None = None, badge: str | None = None):
    # Public reads also clean stale departure dates from JSON storage.
    # A past date inside a chain is deleted, but the tour itself remains.
    items = [t for t in _prune_all_tour_departure_dates() if t.get("active", True)]

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

    if not tour or not tour.get("active", True):
        raise HTTPException(status_code=404, detail="Тур не найден")

    return tour



@api.get("/reviews")
async def get_reviews():
    items = [r for r in list_items("reviews") if r.get("active", True)]
    items.sort(key=_order_value)
    return items


@api.get("/articles")
async def get_articles():
    items = [a for a in list_items("articles") if a.get("active", True)]
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
    lead["ip"] = request.client.host if request.client else None
    lead["user_agent"] = request.headers.get("user-agent")
    lead["page_url"] = lead.get("page_url") or request.headers.get("referer")

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
async def login(payload: LoginIn):
    user = authenticate(payload.email, payload.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    token = create_access_token(user["email"])
    return {"token": token, "user": user}


@api.get("/auth/me")
async def me(current=Depends(get_current_admin)):
    return current


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

    ext = Path(file.filename or "").suffix.lower()

    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    filename = f"{uuid.uuid4()}{ext}"
    path = UPLOAD_DIR / filename

    content = await file.read()

    # 2 MB лимит уже после сжатия на фронте
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    path.write_bytes(content)

    return {"url": f"/uploads/{filename}"}


# ---------- Admin CRUD -----------------------------------------------------


def _crud_create(name: str, payload: dict) -> dict:
    item = {**payload, "id": str(uuid.uuid4())}

    if "active" not in item:
        item["active"] = True

    if name == "tours":
        _prune_tour_departure_dates(item)

    add_item(name, item)
    return item


def _crud_update(name: str, item_id: str, payload: dict) -> dict:
    if name == "tours":
        payload = {**payload}
        _prune_tour_departure_dates(payload)

    updated = update_item(name, item_id, payload)

    if not updated:
        raise HTTPException(status_code=404, detail="Не найдено")

    return updated


def _crud_delete(name: str, item_id: str) -> dict:
    ok = delete_item(name, item_id)

    if not ok:
        raise HTTPException(status_code=404, detail="Не найдено")

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
    return load("settings", default={})


@api.put("/admin/settings")
async def admin_update_settings(payload: dict, current=Depends(get_current_admin)):
    save("settings", payload)
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
    path = "/" + full_path.strip("/")

    if path.startswith("/api"):
        raise HTTPException(status_code=404, detail="API route not found")

    public_file = _safe_frontend_file(full_path)
    if public_file:
        return public_file

    redirect_to = get_redirect_target(path)
    if redirect_to:
        return RedirectResponse(redirect_to, status_code=301)

    html = render_index_html(path)

    if not html:
        raise HTTPException(
            status_code=404,
            detail=(
                "React build not found. Run `npm run build` in frontend and set "
                "FRONTEND_BUILD_DIR if build is not at ../frontend/build."
            ),
        )

    return HTMLResponse(html)


# ---------- Startup --------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    seed_admin()
    run_seed()

    logger.info("Tour operator API started.")
    logger.info("Data dir: %s", str(STORAGE_DATA_DIR))
    logger.info("Uploads dir: %s", str(UPLOAD_DIR))
    logger.info("Frontend build dir: %s", str(FRONTEND_BUILD_DIR))