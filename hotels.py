"""Canonical hotels and their many-to-many links with tours.

Hotel content lives in ``hotels.json``. A tour stores only lightweight
references in ``hotels`` arrays, so disconnecting a hotel never deletes it and
one hotel can be connected to several tours.
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
seo_nofollow seo_canonical_url map_url updated_at created_at
""".split())
HOTEL_SLUG_MIGRATIONS = {
    "smile-8bbdce1dc467": "kobuleti-smile",
    "sweet-house-b25b6de019d6": "kobuleti-sweet-house",
    "amirani-726d3fddff7c": "kobuleti-amirani",
}
LEGACY_ANCHOR_SLUGS = {
    "sweet-house": "kobuleti-sweet-house",
    "amirani": "kobuleti-amirani",
}


def _migrated_slug(source):
    current = str(source.get("hotel_slug") or "").strip()
    if current in HOTEL_SLUG_MIGRATIONS:
        return HOTEL_SLUG_MIGRATIONS[current]
    anchor = str(source.get("anchor_slug") or "").strip()
    target = LEGACY_ANCHOR_SLUGS.get(anchor)
    if target and (not current or re.fullmatch(rf"{re.escape(anchor)}-[0-9a-f]{{12}}", current)):
        return target
    return current


def revision(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def hotel_groups(tour):
    if tour.get("hotels"):
        yield "legacy", tour
    for index, chain in enumerate(tour.get("chains") or []):
        if isinstance(chain, dict):
            yield str(chain.get("id") or f"chain-{index}"), chain


def _derived_name(group):
    return (
        re.sub(r"^.*?для\s+отеля\s+", "", str(group.get("title") or ""), flags=re.I)
        or "Отель"
    )


def _generated_hotel_id(tour, group_id, index):
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f'travelspace/{tour.get("id")}/{group_id}/{index}',
    ))


def _generated_slug(hotel):
    key = str(hotel.get("id") or hotel.get("name") or uuid.uuid4())
    suffix = hashlib.sha256(key.encode()).hexdigest()[:12]
    prefix = re.sub(
        r"[^a-z0-9-]", "", str(hotel.get("anchor_slug") or "otel").lower()
    ).strip("-") or "otel"
    return f"{prefix[:50]}-{suffix}"


def hotel_slug(hotel):
    return str(hotel.get("hotel_slug") or "").strip() or _generated_slug(hotel)


def _canonical_payload(source, hotel_id, group):
    hotel = {key: deepcopy(value) for key, value in source.items() if key in HOTEL_FIELDS}
    hotel["id"] = hotel_id
    hotel["name"] = str(hotel.get("name") or "").strip() or _derived_name(group)
    hotel.setdefault("active", True)
    hotel.setdefault("page_enabled", True)
    source_slug = _migrated_slug(source)
    hotel["hotel_slug"] = (
        source_slug
        or LEGACY_ANCHOR_SLUGS.get(str(source.get("anchor_slug") or "").strip())
        or hotel_slug(hotel)
    )
    if hotel.get("images") and not hotel.get("image"):
        hotel["image"] = hotel["images"][0]
    return hotel


def _hotel_link(source, hotel_id):
    link = {"hotel_id": hotel_id, "id": hotel_id}
    for key in ("order", "anchor_slug"):
        if source.get(key) not in (None, ""):
            link[key] = deepcopy(source[key])
    return link


def migrate_hotel_catalog(tours, catalog):
    """Move legacy embedded profiles into the canonical catalog in place."""
    changed = False
    for hotel in catalog:
        migrated_slug = _migrated_slug(hotel)
        if migrated_slug and migrated_slug != hotel.get("hotel_slug"):
            hotel["hotel_slug"] = migrated_slug
            changed = True
    by_id = {str(item.get("id")): item for item in catalog if item.get("id")}
    for tour in tours:
        for group_id, group in hotel_groups(tour):
            normalized = []
            for index, source in enumerate(group.get("hotels") or []):
                if not isinstance(source, dict):
                    changed = True
                    continue
                hotel_id = str(
                    source.get("hotel_id")
                    or source.get("id")
                    or _generated_hotel_id(tour, group_id, index)
                )
                if hotel_id not in by_id:
                    canonical = _canonical_payload(source, hotel_id, group)
                    catalog.append(canonical)
                    by_id[hotel_id] = canonical
                    changed = True
                link = _hotel_link(source, hotel_id)
                normalized.append(link)
                if source != link:
                    changed = True
            if group.get("hotels") != normalized:
                group["hotels"] = normalized
                changed = True
    return changed


def ensure_hotel_ids(tour):
    """Normalize hotel references while retaining the old public helper."""
    for group_id, group in hotel_groups(tour):
        seen = set()
        normalized = []
        for index, source in enumerate(group.get("hotels") or []):
            if not isinstance(source, dict):
                continue
            hotel_id = str(
                source.get("hotel_id")
                or source.get("id")
                or _generated_hotel_id(tour, group_id, index)
            )
            if hotel_id in seen:
                continue
            seen.add(hotel_id)
            normalized.append(_hotel_link(source, hotel_id))
        group["hotels"] = normalized
    return tour


def tour_hotels_revision(tour):
    return revision([
        (key, group.get("active"), group.get("dates"), group.get("hotels"))
        for key, group in hotel_groups(tour)
    ])


def _connection_dates(tour, group):
    if tour.get("use_hotel_chains") and tour.get("show_chain_dates") is not False:
        dates = group.get("dates") or []
    else:
        dates = tour.get("dates") or []
    return deepcopy(dates)


def _connection(tour, group_id, group, hotel_id):
    return {
        "id": f'{tour.get("id")}~{group_id}',
        "tour_id": tour.get("id"),
        "tour_slug": tour.get("slug"),
        "tour_title": tour.get("title"),
        "tour_tagline": tour.get("tagline") or tour.get("short_description") or "",
        "tour_image": tour.get("image") or next(iter(tour.get("images") or []), ""),
        "tour_duration": tour.get("duration") or tour.get("duration_days"),
        "price_from": tour.get("price_from"),
        "price_usd": tour.get("price_usd"),
        "price_byn": tour.get("price_byn"),
        "currency": tour.get("currency"),
        "chain_id": group_id,
        "chain_title": group.get("title") or "Основные даты тура",
        "dates": _connection_dates(tour, group),
        "tour_hotel_anchor": f"hotel-{hotel_id}",
        "tour_active": tour.get("active") is not False,
        "chain_active": group.get("active") is not False,
    }


def hotel_records(tours, catalog=None, public=False):
    """Return canonical hotel records enriched with every connected tour."""
    catalog = catalog or []
    connections = {str(hotel.get("id")): [] for hotel in catalog if hotel.get("id")}
    for tour in tours:
        if public and tour.get("active") is False:
            continue
        for group_id, group in hotel_groups(tour):
            if public and group.get("active") is False:
                continue
            for link in group.get("hotels") or []:
                hotel_id = str(link.get("hotel_id") or link.get("id") or "")
                if hotel_id in connections:
                    connections[hotel_id].append(_connection(tour, group_id, group, hotel_id))

    records = []
    for source in catalog:
        if not isinstance(source, dict) or not source.get("id"):
            continue
        if public and (source.get("active") is False or source.get("page_enabled") is False):
            continue
        record = deepcopy(source)
        record["id"] = str(source["id"])
        record["hotel_id"] = record["id"]
        record["slug"] = hotel_slug(record)
        record["hotel_slug"] = record["slug"]
        record["connections"] = connections.get(record["id"], [])
        first = next(
            (item for item in record["connections"] if item.get("tour_active") and item.get("chain_active")),
            record["connections"][0] if record["connections"] else {},
        )
        for key in (
            "tour_id", "tour_slug", "tour_title", "chain_id", "chain_title",
            "dates", "tour_hotel_anchor", "tour_active", "chain_active",
        ):
            record[key] = deepcopy(first.get(key))
        record["revision"] = revision({key: value for key, value in source.items() if key != "revision"})
        if public:
            record.pop("revision", None)
            record["connections"] = [
                item for item in record["connections"]
                if item.get("tour_active") and item.get("chain_active")
            ]
            record["rooms"] = [
                room for room in record.get("rooms") or []
                if isinstance(room, dict) and room.get("active") is not False
            ]
        records.append(record)
    return records


def decorate_tour(tour, catalog=None, admin=False):
    result = deepcopy(tour)
    catalog_by_id = {
        str(hotel.get("id")): hotel for hotel in (catalog or [])
        if isinstance(hotel, dict) and hotel.get("id")
    }
    if admin:
        result["_hotels_revision"] = tour_hotels_revision(result)
    for _, group in hotel_groups(result):
        hydrated = []
        for link in group.get("hotels") or []:
            hotel_id = str(link.get("hotel_id") or link.get("id") or "")
            source = catalog_by_id.get(hotel_id)
            if not source:
                continue
            hotel = deepcopy(source)
            hotel["hotel_id"] = hotel_id
            hotel["id"] = hotel_id
            hotel["hotel_slug"] = hotel_slug(hotel)
            hotel["hotel_page_slug"] = (
                hotel["hotel_slug"]
                if hotel.get("active") is not False and hotel.get("page_enabled") is not False
                else ""
            )
            hydrated.append(hotel)
        group["hotels"] = hydrated
    return result


def validate_hotel(hotel):
    if not str(hotel.get("name") or "").strip():
        raise HTTPException(422, "Укажите название отеля.")
    slug = str(hotel.get("hotel_slug") or "").strip()
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(422, "Адрес отеля: только латинские буквы в нижнем регистре, цифры и дефис.")
    if len(slug) > 100:
        raise HTTPException(422, "Адрес отеля слишком длинный (не более 100 символов).")
    hotel["hotel_slug"] = slug or _generated_slug(hotel)
    for field in ("images", "image_alts", "rooms", "amenities", "nearby"):
        if field in hotel and not isinstance(hotel[field], list):
            raise HTTPException(422, f"Поле {field} должно быть списком.")
    if any(not isinstance(room, dict) for room in hotel.get("rooms") or []):
        raise HTTPException(422, "Проверьте список номеров отеля.")
    map_url = str(hotel.get("map_url") or "").strip()
    if map_url and not re.match(r"^https?://[^\s]+$", map_url):
        raise HTTPException(422, "Для карты укажите ссылку https://, а не код iframe.")
    hotel["map_url"] = map_url


def _normalize_tour_links(tour, catalog):
    known = {str(item.get("id")) for item in catalog if item.get("id")}
    for _, group in hotel_groups(tour):
        normalized = []
        seen = set()
        for source in group.get("hotels") or []:
            if not isinstance(source, dict):
                continue
            hotel_id = str(source.get("hotel_id") or source.get("id") or "")
            if not hotel_id or hotel_id not in known:
                raise HTTPException(422, "Один из подключённых отелей больше не существует.")
            if hotel_id in seen:
                continue
            seen.add(hotel_id)
            normalized.append(_hotel_link(source, hotel_id))
        group["hotels"] = normalized


def validate_tour_hotels(tours, tour, catalog=None):
    _normalize_tour_links(tour, catalog or [])


def edit_hotel(catalog, tours, payload, item_id=None, delete=False, timestamp=""):
    existing = next(
        (item for item in catalog if str(item.get("id")) == str(item_id)), None
    ) if item_id else None
    if item_id and not existing:
        raise HTTPException(404, "Отель не найден")
    if delete:
        catalog[:] = [item for item in catalog if str(item.get("id")) != str(item_id)]
        for tour in tours:
            changed = False
            for _, group in hotel_groups(tour):
                before = group.get("hotels") or []
                after = [link for link in before if str(link.get("hotel_id") or link.get("id")) != str(item_id)]
                if before != after:
                    group["hotels"] = after
                    changed = True
            if changed:
                tour["updated_at"] = timestamp
        return {"ok": True}

    hotel_id = str(item_id or uuid.uuid4())
    if existing:
        expected = hotel_records([], [existing])[0]["revision"]
        if payload.get("revision") not in (None, expected):
            raise HTTPException(409, "Отель уже изменён в другой вкладке. Откройте запись заново перед сохранением.")
    hotel = deepcopy(existing) if existing else {
        "id": hotel_id, "active": True, "page_enabled": True, "created_at": timestamp,
    }
    hotel.update({key: deepcopy(value) for key, value in payload.items() if key in HOTEL_FIELDS})
    hotel["id"] = hotel_id
    hotel["updated_at"] = timestamp
    if hotel.get("images"):
        hotel["image"] = hotel["images"][0]
    validate_hotel(hotel)
    slug = hotel_slug(hotel)
    if any(str(item.get("id")) != hotel_id and hotel_slug(item) == slug for item in catalog):
        raise HTTPException(409, "Этот адрес страницы отеля уже занят. Укажите другой URL.")
    if existing:
        existing.clear()
        existing.update(hotel)
    else:
        catalog.append(hotel)
    return next(item for item in hotel_records(tours, catalog) if item["id"] == hotel_id)
