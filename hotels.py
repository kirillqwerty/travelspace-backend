"""Hotel entities backed by the owning tour's hotel record (one source of truth).

Dates, room prices and availability remain in their original chain. Both admin
editors modify that same JSON record; no background synchronization is needed.
"""
from copy import deepcopy
import hashlib
import json
import re
import uuid

from fastapi import HTTPException


HOTEL_FIELDS = set("""
name description short_description images image image_alts meal meal_description
location address location_description nearby amenities beach transfer check_in
check_out rules rooms active order anchor_slug hotel_slug page_enabled stars
youtube_url youtube_title seo_title seo_description seo_image seo_noindex
seo_nofollow seo_canonical_url map_url updated_at
""".split())


def hotel_groups(tour):
    if tour.get("hotels"):
        yield "legacy", tour
    for index, chain in enumerate(tour.get("chains") or []):
        if isinstance(chain, dict):
            yield str(chain.get("id") or f"chain-{index}"), chain


def hotel_slug(tour, hotel):
    if hotel.get("hotel_slug"):
        return hotel["hotel_slug"]
    key = f'{tour.get("id")}/{hotel.get("id")}'
    suffix = hashlib.sha256(key.encode()).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9-]", "", str(hotel.get("anchor_slug") or "otel").lower()).strip("-") or "otel"
    return f"{prefix[:50]}-{suffix}"


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def tour_hotels_revision(tour):
    return revision([(key, group.get("active"), group.get("dates"), group.get("hotels")) for key, group in hotel_groups(tour)])


def ensure_hotel_ids(tour):
    """Deterministic IDs support legacy records without changing their anchors."""
    seen = set()
    for key, group in hotel_groups(tour):
        for index, hotel in enumerate(group.get("hotels") or []):
            if not hotel.get("id") or hotel["id"] in seen:
                hotel["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f'travelspace/{tour.get("id")}/{key}/{index}'))
            seen.add(hotel["id"])
    return tour


def hotel_records(tours, public=False):
    records = []
    for original in tours:
        tour = ensure_hotel_ids(deepcopy(original))
        if public and tour.get("active") is False:
            continue
        for chain_id, group in hotel_groups(tour):
            if public and group.get("active") is False:
                continue
            for hotel in group.get("hotels") or []:
                if public and (hotel.get("active") is False or hotel.get("page_enabled") is False):
                    continue
                name = hotel.get("name") or re.sub(r"^.*?для\s+отеля\s+", "", group.get("title") or "", flags=re.I) or "Отель"
                record = {key: deepcopy(value) for key, value in hotel.items() if key in HOTEL_FIELDS}
                record.update({
                    "id": f'{tour["id"]}~{hotel["id"]}', "hotel_id": hotel["id"],
                    "slug": hotel_slug(tour, hotel), "name": name,
                    "tour_id": tour["id"], "tour_slug": tour.get("slug"), "tour_title": tour.get("title"),
                    "chain_id": chain_id, "chain_title": group.get("title") or "Основная цепочка",
                    "dates": deepcopy(group.get("dates") or []),
                    "tour_active": tour.get("active") is not False,
                    "chain_active": group.get("active") is not False,
                    "revision": revision([hotel, group.get("dates")]),
                })
                record["hotel_slug"] = record["slug"]
                record["tour_hotel_anchor"] = f'hotel-{hotel["id"]}'
                if public:
                    record.pop("revision", None)
                    record["rooms"] = [room for room in record.get("rooms") or [] if room.get("active") is not False]
                records.append(record)
    return records


def decorate_tour(tour, admin=False):
    result = ensure_hotel_ids(deepcopy(tour))
    if admin:
        result["_hotels_revision"] = tour_hotels_revision(result)
    for _, group in hotel_groups(result):
        for hotel in group.get("hotels") or []:
            hotel["hotel_page_slug"] = hotel_slug(result, hotel) if hotel.get("active") is not False and hotel.get("page_enabled") is not False else ""
            if admin:
                hotel["hotel_slug"] = hotel_slug(result, hotel)
    return result


def validate_hotel(hotel):
    slug = str(hotel.get("hotel_slug") or "").strip()
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(422, "Адрес отеля: только латинские буквы в нижнем регистре, цифры и дефис.")
    if len(slug) > 100:
        raise HTTPException(422, "Адрес отеля слишком длинный (не более 100 символов).")
    hotel["hotel_slug"] = slug
    for field in ("images", "image_alts", "rooms", "amenities", "nearby"):
        if field in hotel and not isinstance(hotel[field], list):
            raise HTTPException(422, f"Поле {field} должно быть списком.")
    if any(not isinstance(room, dict) for room in hotel.get("rooms") or []):
        raise HTTPException(422, "Проверьте список номеров отеля.")
    map_url = str(hotel.get("map_url") or "").strip()
    if map_url and not re.match(r"^https?://[^\s]+$", map_url):
        raise HTTPException(422, "Для карты укажите ссылку https://, а не код iframe.")
    hotel["map_url"] = map_url


def validate_tour_hotels(tours, tour):
    ensure_hotel_ids(tour)
    existing_slugs = {r["slug"] for r in hotel_records([t for t in tours if t.get("id") != tour.get("id")])}
    for _, group in hotel_groups(tour):
        for hotel in group.get("hotels") or []:
            hotel.pop("hotel_page_slug", None)
            validate_hotel(hotel)
            slug = hotel_slug(tour, hotel)
            if slug in existing_slugs:
                raise HTTPException(409, "Этот адрес страницы отеля уже занят. Укажите другой URL.")
            existing_slugs.add(slug)


def edit_hotel(tours, payload, item_id=None, delete=False, timestamp=""):
    existing = next((r for r in hotel_records(tours) if r["id"] == item_id), None) if item_id else None
    if item_id and not existing:
        raise HTTPException(404, "Отель не найден")
    if existing and not delete and payload.get("revision") != existing["revision"]:
        raise HTTPException(409, "Отель или его даты уже изменены в другой вкладке. Откройте запись заново перед сохранением.")
    owner_id = existing["tour_id"] if existing else payload.get("tour_id")
    chain_id = existing["chain_id"] if existing else payload.get("chain_id")
    tour = next((t for t in tours if t.get("id") == owner_id), None)
    if not tour:
        raise HTTPException(422, "Выберите существующий тур.")
    ensure_hotel_ids(tour)
    if chain_id == "legacy":
        group = tour
    elif chain_id == "new" and not existing:
        if tour.get("dates") or tour.get("hotels"):
            raise HTTPException(422, "Сначала включите отели и цепочки в настройках тура, чтобы сохранить текущие даты.")
        group = {"id": str(uuid.uuid4()), "title": f'Расписание туров для отеля {str(payload.get("name") or "").strip()}', "active": True, "dates": [], "hotels": []}
        tour.setdefault("chains", []).append(group)
    else:
        group = next((c for i, c in enumerate(tour.get("chains") or []) if str(c.get("id") or f"chain-{i}") == chain_id), None)
    if group is None:
        raise HTTPException(422, "Выберите цепочку с датами в настройках тура.")
    hotels = group.setdefault("hotels", [])
    if delete:
        group["hotels"] = [h for h in hotels if h.get("id") != existing["hotel_id"]]
        tour["updated_at"] = timestamp
        return {"ok": True}
    if not str(payload.get("name") or "").strip():
        raise HTTPException(422, "Укажите название отеля.")
    hotel = next((h for h in hotels if existing and h.get("id") == existing["hotel_id"]), None)
    if hotel is None:
        hotel = {"id": str(uuid.uuid4()), "active": True, "page_enabled": True}
        hotels.append(hotel)
    hotel.update({key: deepcopy(value) for key, value in payload.items() if key in HOTEL_FIELDS})
    hotel["updated_at"] = timestamp
    if "images" in hotel:
        hotel["image"] = next(iter(hotel["images"]), "")
    tour["updated_at"] = timestamp
    tour["use_hotel_chains"] = True
    validate_tour_hotels(tours, tour)
    target_id = f'{tour["id"]}~{hotel["id"]}'
    return next(r for r in hotel_records([tour]) if r["id"] == target_id)
