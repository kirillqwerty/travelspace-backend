"""FastAPI server for the tour operator site.

Storage: JSON files in /app/backend/data/ (no MongoDB usage).
Auth: JWT for the admin panel.
All API routes are prefixed with /api.

NOTE: "Направление" entity has been REMOVED. Tours now contain all the
information that used to live on directions (tagline, description, gallery,
highlights, what_to_see, FAQ). Tours are grouped by ``region_slug`` /
``region_name`` for filtering and specialist routing only.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, EmailStr  # noqa: E402

from auth import authenticate, create_access_token, get_current_admin, seed_admin  # noqa: E402
from seed import run_seed  # noqa: E402
from storage import (  # noqa: E402
    add_item,
    delete_item,
    get_by,
    list_items,
    load,
    save,
    update_item,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("travelspace")

app = FastAPI(title="Tour Operator API")
api = APIRouter(prefix="/api")
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

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
    specialist: str | None = None
    consent: bool = True
    form_type: str = "consultation"  # consultation | tour | agency
    extra: dict | None = None


class LeadStatusIn(BaseModel):
    status: str  # new | in_progress | closed


# ---------- Helpers --------------------------------------------------------

PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,}$")


def _ensure_phone(phone: str) -> str:
    if not phone or not PHONE_RE.match(phone.strip()):
        raise HTTPException(status_code=422, detail="Введите корректный номер телефона")
    return phone.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(extra: dict | None = None) -> dict:
    return {"ok": True, **(extra or {})}

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


def _is_tour_expired(tour: dict) -> bool:
    tomorrow = date.today() + timedelta(days=1)

    start_dates = [
        parsed
        for parsed in (_parse_date(d.get("start")) for d in _tour_dates(tour))
        if parsed
    ]

    if not start_dates:
        return False

    return not any(start_date > tomorrow for start_date in start_dates)



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
    items = [t for t in list_items("tours") if t.get("active", True)]
    if region:
        items = [t for t in items if t.get("region_slug") == region]
    if badge:
        items = [t for t in items if badge in (t.get("badges") or [])]
    items.sort(key=_order_value)
    return items


@api.get("/tours/{slug}")
async def get_tour(slug: str):
    t = get_by("tours", "slug", slug)
    if not t or not t.get("active", True) or _is_tour_expired(t):
        raise HTTPException(status_code=404, detail="Тур не найден")
    return t


@api.get("/specialists")
async def get_specialists(region: str | None = None):
    items = [s for s in list_items("specialists") if s.get("active", True)]
    if region:
        items = [s for s in items if region in (s.get("regions") or [])]
    items.sort(key=_order_value)
    return items


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
    a = get_by("articles", "slug", slug)
    if not a or not a.get("active", True):
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return a


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
async def create_lead(payload: LeadIn):
    phone = _ensure_phone(payload.phone)
    if not payload.consent:
        raise HTTPException(status_code=422, detail="Необходимо согласие на обработку персональных данных")
    lead = payload.model_dump()
    lead["phone"] = phone
    lead["id"] = str(uuid.uuid4())
    lead["status"] = "new"
    lead["created_at"] = _now()
    add_item("leads", lead)
    logger.info("New lead saved: id=%s phone=%s tour=%s", lead["id"], phone, payload.tour_slug)
    return _ok({"id": lead["id"]})


# ---------- Auth -----------------------------------------------------------


@api.post("/auth/login", response_model=LoginOut)
async def login(payload: LoginIn):
    user = authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
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
        raise HTTPException(status_code=400, detail="Можно загружать только изображения")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    filename = f"{uuid.uuid4()}{ext}"
    path = UPLOAD_DIR / filename

    content = await file.read()

    # 2 MB лимит уже ПОСЛЕ сжатия на фронте
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    path.write_bytes(content)

    return {
        "url": f"/uploads/{filename}"
    }
# ---------- Admin CRUD -----------------------------------------------------


def _crud_create(name: str, payload: dict) -> dict:
    item = {**payload, "id": str(uuid.uuid4())}
    if "active" not in item:
        item["active"] = True
    add_item(name, item)
    return item


def _crud_update(name: str, item_id: str, payload: dict) -> dict:
    updated = update_item(name, item_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Не найдено")
    return updated


def _crud_delete(name: str, item_id: str) -> dict:
    ok = delete_item(name, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Не найдено")
    return _ok()


# Generic admin endpoints for each collection.
# "directions" is intentionally NOT in this list — the entity has been removed.
# Note: leads endpoints (declared further below) are registered FIRST so that
# /admin/leads/{id} doesn't match the generic /admin/{collection}/{item_id}.
COLLECTIONS = ["tours", "specialists", "reviews", "articles", "faq", "promotions"]


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
async def admin_leads_update(item_id: str, payload: LeadStatusIn, current=Depends(get_current_admin)):
    return _crud_update("leads", item_id, {"status": payload.status})


@api.delete("/admin/leads/{item_id}")
async def admin_leads_delete(item_id: str, current=Depends(get_current_admin)):
    return _crud_delete("leads", item_id)


@api.get("/admin/{collection}")
async def admin_list(collection: str, current=Depends(get_current_admin)):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")
    return list_items(collection)


@api.post("/admin/{collection}")
async def admin_create(collection: str, payload: dict, current=Depends(get_current_admin)):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")
    return _crud_create(collection, payload)


@api.put("/admin/{collection}/{item_id}")
async def admin_update(collection: str, item_id: str, payload: dict, current=Depends(get_current_admin)):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")
    return _crud_update(collection, item_id, payload)


@api.delete("/admin/{collection}/{item_id}")
async def admin_delete(collection: str, item_id: str, current=Depends(get_current_admin)):
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=404, detail="Unknown collection")
    return _crud_delete(collection, item_id)


# ---------- Mount router & CORS -------------------------------------------


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    seed_admin()
    run_seed()
    logger.info("Tour operator API started. Data dir: %s", str(Path(__file__).parent / "data"))
