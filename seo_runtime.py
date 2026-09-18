"""Server-side SEO rendering for the React application.

Search engines receive unique metadata and a semantic HTML snapshot for every
public URL. React replaces the snapshot after it starts in the browser.
"""

from __future__ import annotations

from article_content import article_blocks
from hotels import decorate_tour, hotel_records

import json
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from rich_text import render_inline, plain_text
from homepage import home_benefits_content, home_page_content, is_home_faq
from storage import get_by, list_items, load

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
FRONTEND_BUILD_DIR = Path(
    os.environ.get("FRONTEND_BUILD_DIR") or PROJECT_DIR / "frontend" / "build"
)
INDEX_HTML_PATH = FRONTEND_BUILD_DIR / "index.html"
# API origin may be localhost in development; canonical URLs must stay on the
# one public host. Override only through the dedicated SEO setting.
PUBLIC_SITE_URL = os.environ.get("CANONICAL_SITE_URL", "https://travelspace.by").rstrip("/")
SITE_NAME = "TRAVELSPACE"
DEFAULT_TITLE = "TRAVELSPACE — автобусные и авиа туры из Минска"
DEFAULT_DESCRIPTION = (
    "Авторские автобусные и авиа туры из Минска: Грузия, Дагестан, "
    "Санкт-Петербург, Карелия и другие направления."
)
DEFAULT_IMAGE = "/og-image.jpg"


STATIC_PAGE_FALLBACKS: dict[str, dict[str, str]] = {
    "/": {
        "title": "TRAVELSPACE — автобусные и авиа туры из Минска",
        "description": "Туры из Минска в Грузию, Дагестан, Санкт-Петербург, Карелию, Турцию и другие направления.",
        "heading": "Авторские туры из Минска",
    },
    "/tours": {
        "title": "Каталог туров из Минска | TRAVELSPACE",
        "description": "Актуальные автобусные и авиа туры из Минска: даты, цены, программа и бронирование.",
        "heading": "Все туры из Минска",
    },
    "/about": {
        "title": "О компании TRAVELSPACE — туроператор из Минска",
        "description": "TRAVELSPACE разрабатывает авторские туры из Минска и сопровождает туристов на всём маршруте.",
        "heading": "О компании TRAVELSPACE",
    },
    "/contacts": {
        "title": "Контакты TRAVELSPACE",
        "description": "Телефоны, email, офис, режим работы и форма заявки на подбор тура.",
        "heading": "Контакты TRAVELSPACE",
    },
    "/faq": {
        "title": "Частые вопросы о турах | TRAVELSPACE",
        "description": "Ответы на вопросы о бронировании, оплате, документах и поездках с TRAVELSPACE.",
        "heading": "Частые вопросы о турах",
    },
    "/promotions": {
        "title": "Акции и спецпредложения на туры | TRAVELSPACE",
        "description": "Актуальные акции, скидки и специальные предложения на туры из Минска.",
        "heading": "Акции и спецпредложения",
    },
    "/reviews": {
        "title": "Отзывы туристов | TRAVELSPACE",
        "description": "Отзывы туристов о поездках, маршрутах и работе TRAVELSPACE.",
        "heading": "Отзывы туристов",
    },
    "/blog": {
        "title": "Блог о путешествиях | TRAVELSPACE",
        "description": "Полезные статьи, подборки и советы для комфортных путешествий.",
        "heading": "Блог о путешествиях",
    },
    "/agencies": {
        "title": "Агентствам — сотрудничество с TRAVELSPACE",
        "description": "Условия сотрудничества для турагентств: места, материалы и поддержка менеджера.",
        "heading": "Сотрудничество с турагентствами",
    },
    "/payment": {
        "title": "Оплата тура через ЕРИП | TRAVELSPACE",
        "description": "Как оплатить тур TRAVELSPACE через ЕРИП после бронирования и заключения договора.",
        "heading": "Оплата тура",
    },
    "/legal": {
        "title": "Юридическая информация | TRAVELSPACE",
        "description": "Политика конфиденциальности, обработка персональных данных, договор и реквизиты TRAVELSPACE.",
        "heading": "Юридическая информация",
    },
}


EMPTY_LANDING_CONTENT: dict[str, Any] = {
    "catalog_title": "Выберите подходящий тур",
    "cover_image": "",
    "cover_alt": "",
    "youtube_title": "",
    "youtube_url": "",
    "content_title": "",
    "content_body": "",
    "content_sections": [],
    "how_to_title": "Как выбрать тур",
    "faq_title": "",
    "faq_items": [],
}

BUS_LANDING_CONTENT: dict[str, Any] = {
    "content_title": "Автобусные туры из Беларуси: направления, цены и формат поездок",
    "content_body": (
        "Автобусные туры из Минска подходят для экскурсионных поездок, отдыха у моря и путешествий по природным маршрутам. "
        "В одном месте можно сравнить даты, продолжительность, программу и стоимость, а затем открыть страницу выбранного тура и изучить подробности.\n\n"
        "В каталоге собраны актуальные [автобусные туры из Минска](/tours): доступность мест и окончательную стоимость на выбранную дату подтверждает менеджер TRAVELSPACE. "
        "Такой формат помогает заранее оценить бюджет и выбрать поездку, которая подходит по темпу, маршруту и продолжительности."
    ),
    "content_sections": [
        {
            "title": "Экскурсионные автобусные туры",
            "text": "Для насыщенной экскурсионной программы подойдут поездки в [Санкт-Петербург](/tours/sankt-peterburg), [Дагестан](/tours/dagestan), [Карелию](/tours/kareliya) и [Арктику](/tours/arktika). На странице каждого направления собраны подходящие программы, ближайшие даты и основные условия поездки.",
        },
        {
            "title": "Автобусные туры на море",
            "text": "Поездки в [Грузию](/tours/gruziya) и [Абхазию](/tours/abhaziya) позволяют совместить организованный переезд, проживание, отдых у моря и экскурсии. Перед бронированием сравните продолжительность отдыха, расположение отеля и услуги, включённые в стоимость.",
        },
        {
            "title": "Откуда отправляются автобусы",
            "text": "Основным городом отправления является Минск. Возможные посадки в других городах Беларуси зависят от конкретного маршрута и даты. Актуальные города и точки посадки указаны на странице тура; при оформлении заявки менеджер подтвердит удобный вариант.",
        },
        {
            "title": "Что входит в стоимость поездки",
            "text": "Состав стоимости зависит от программы. Обычно отдельно указаны проезд, проживание, экскурсии, питание и дополнительные расходы. Проверяйте блоки «В стоимость включено» и «В стоимость не включено» на странице выбранного тура, чтобы корректно сравнить предложения.",
        },
    ],
    "how_to_title": "Как выбрать автобусный тур из Минска",
    "faq_title": "Частые вопросы об автобусных турах из Минска",
    "faq_items": [
        {
            "question": "Какие автобусные туры из Минска доступны сейчас?",
            "answer": "Актуальные программы и даты показаны в каталоге выше. Если подходящей даты пока нет, оставьте заявку — менеджер проверит ближайшие выезды и предложит альтернативы.",
        },
        {
            "question": "Куда можно поехать на автобусе из Беларуси?",
            "answer": "В каталоге представлены экскурсионные поездки и туры на море. Среди направлений — Санкт-Петербург, Дагестан, Карелия, Арктика, Грузия, Абхазия и другие маршруты.",
        },
        {
            "question": "Из каких городов Беларуси есть отправления?",
            "answer": "Основной город отправления — Минск. Дополнительные города посадки зависят от маршрута и даты и указываются на странице конкретного тура.",
        },
        {
            "question": "Что входит в стоимость автобусного тура?",
            "answer": "Для каждого тура состав стоимости указан отдельно. На странице программы можно проверить, включены ли проезд, проживание, экскурсии и питание, а также увидеть возможные дополнительные расходы.",
        },
        {
            "question": "Сколько обычно длится автобусный тур?",
            "answer": "Продолжительность зависит от направления и программы. Количество дней и ночей указано в карточке и на подробной странице каждого тура.",
        },
        {
            "question": "Можно ли выбрать место в автобусе?",
            "answer": "Возможность выбора места зависит от конкретной поездки и схемы автобуса. Сообщите пожелание менеджеру при бронировании — он уточнит доступные варианты.",
        },
        {
            "question": "Как забронировать автобусный тур?",
            "answer": "Выберите программу и дату, затем оставьте заявку на сайте. Менеджер свяжется с вами, подтвердит наличие мест, итоговую стоимость и порядок оформления.",
        },
        {
            "question": "Какие документы нужны для поездки?",
            "answer": "Перечень документов зависит от страны, маршрута и возраста туриста. Перед оплатой менеджер сообщит актуальные требования для выбранной поездки.",
        },
    ],
}


LANDING_PAGES: dict[str, dict[str, Any]] = {
    "/tours/avtobusnye-iz-minska": {
        "title": "Автобусные туры из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры из Минска в Грузию, Дагестан, Санкт-Петербург, Карелию, Абхазию и другие направления.",
        "heading": "Автобусные туры из Минска",
        "intro": "Готовые групповые маршруты с продуманной программой, сопровождением и удобными датами выезда. Сравните направления и выберите подходящую поездку.",
        **BUS_LANDING_CONTENT,
        "kind": "bus",
    },
    "/tours/avia-iz-minska": {
        "title": "Авиа туры из Минска 2026 | TRAVELSPACE",
        "description": "Туры с перелётом из Минска: актуальные направления, программы, даты и стоимость поездок.",
        "heading": "Авиа туры из Минска",
        "intro": "Путешествия с перелётом для тех, кто хочет быстрее добраться до места отдыха. В карточках указаны программа, даты и состав стоимости.",
        "how_to_title": "Как выбрать авиа тур из Минска",
        "kind": "air",
    },
    "/tours/gruziya": {
        "title": "Туры в Грузию из Минска 2026 | TRAVELSPACE",
        "description": "Туры в Грузию из Минска: отдых на море, экскурсии, даты, программа и стоимость поездки.",
        "heading": "Туры в Грузию из Минска",
        "intro": "Поездки в Грузию сочетают море, горные пейзажи, национальную кухню и экскурсии. На странице собраны актуальные программы TRAVELSPACE.",
        "how_to_title": "Как выбрать тур в Грузию из Минска",
        "keywords": ("груз", "gruzi"),
    },
    "/tours/sankt-peterburg": {
        "title": "Автобусный тур в Санкт-Петербург из Минска | TRAVELSPACE",
        "description": "Туры в Санкт-Петербург и Питер из Минска на выходные: программа, даты, отели и стоимость.",
        "heading": "Туры в Санкт-Петербург из Минска",
        "intro": "Автобусные поездки в Санкт-Петербург из Минска с насыщенной экскурсионной программой. Выберите дату и изучите подробный маршрут тура.",
        "how_to_title": "Как выбрать тур в Санкт-Петербург из Минска",
        "keywords": ("петербург", "питер", "peterburg"),
    },
    "/tours/dagestan": {
        "title": "Туры в Дагестан из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Дагестан из Минска: горы, каньоны, экскурсии, даты и стоимость.",
        "heading": "Туры в Дагестан из Минска",
        "intro": "Горные маршруты, Сулакский каньон, древние аулы и Каспийское море в одной поездке. Ниже — актуальные программы и даты.",
        "how_to_title": "Как выбрать тур в Дагестан из Минска",
        "keywords": ("дагест", "dagestan"),
    },
    "/tours/kareliya": {
        "title": "Туры в Карелию из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Карелию из Минска: Рускеала, Кижи, Ладожские шхеры, даты и программа.",
        "heading": "Туры в Карелию из Минска",
        "intro": "Карельская природа, горный парк Рускеала, остров Кижи и Ладожские шхеры. Сравните программу и доступные даты поездки.",
        "how_to_title": "Как выбрать тур в Карелию из Минска",
        "keywords": ("карел", "kareli"),
    },
    "/tours/abhaziya": {
        "title": "Туры в Абхазию из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Абхазию из Минска: море, экскурсии, программа, даты и стоимость.",
        "heading": "Туры в Абхазию из Минска",
        "intro": "Отдых у моря с экскурсионной программой и организованным выездом из Минска. Изучите маршрут, отели и ближайшие даты.",
        "how_to_title": "Как выбрать тур в Абхазию из Минска",
        "keywords": ("абхаз", "abhaz"),
    },
    "/tours/severnaya-osetiya": {
        "title": "Туры в Северную Осетию из Минска | TRAVELSPACE",
        "description": "Автобусные туры в Северную Осетию из Минска: горные маршруты, программа, даты и цены.",
        "heading": "Туры в Северную Осетию из Минска",
        "intro": "Горные ущелья, древние башни и живописные дороги Северной Осетии. На странице собраны доступные программы TRAVELSPACE.",
        "how_to_title": "Как выбрать тур в Северную Осетию из Минска",
        "keywords": ("осети", "oseti"),
    },
    "/tours/moskva": {
        "title": "Автобусные туры в Москву из Минска | TRAVELSPACE",
        "description": "Туры в Москву из Минска на выходные: экскурсионная программа, даты, отель и стоимость.",
        "heading": "Туры в Москву из Минска",
        "intro": "Короткие автобусные поездки в Москву из Минска для насыщенных выходных. Проверьте программу, даты и включённые услуги.",
        "how_to_title": "Как выбрать тур в Москву из Минска",
        "keywords": ("москв", "moskv"),
    },
    "/tours/arktika": {
        "title": "Туры в Арктику из Минска | TRAVELSPACE",
        "description": "Автобусные туры в Арктику из Минска: программа поездки, даты, маршрут и стоимость.",
        "heading": "Туры в Арктику из Минска",
        "intro": "Поездки за Полярный круг, северные пейзажи и необычная экскурсионная программа. На странице появятся актуальные даты и маршруты TRAVELSPACE.",
        "how_to_title": "Как выбрать тур в Арктику из Минска",
        "keywords": ("аркти", "arkti"),
    },
}

SERVICE_PAGES = {"/thanks", "/links"}

BUILT_IN_REDIRECTS = {
    "/directions": "/tours",
    "/directions/georgia-kobuleti": "/tours/gruziya",
    "/directions/saint-petersburg": "/tours/sankt-peterburg",
    "/directions/dagestan": "/tours/dagestan",
    "/directions/kareliya": "/tours/kareliya",
    "/tours/gruziya-kobuleti-10-dney": "/tours/avtobusniy-tur-v-gruziyu",
    "/tours/saint-petersburg-5-dney": "/tours/avtobusniy-tur-v-peterburg-na-vyhodnye",
    "/tours/dagestan-7-dney": "/tours/avtobusniy-tur-v-dagestan",
    "/tours/kareliya-5-dney": "/tours/avtobusniy-tur-v-kareliyu",
}

SEO_TAG_PATTERNS = [
    r"<title(?:\s[^>]*)?>.*?</title>",
    r"<meta\s+name=[\"']description[\"'][^>]*>",
    r"<meta\s+name=[\"']keywords[\"'][^>]*>",
    r"<meta\s+name=[\"']robots[\"'][^>]*>",
    r"<link\s+rel=[\"']canonical[\"'][^>]*>",
    r"<meta\s+property=[\"']og:[^\"']+[\"'][^>]*>",
    r"<meta\s+name=[\"']twitter:[^\"']+[\"'][^>]*>",
    r"<script\s+type=[\"']application/ld\+json[\"'][^>]*>.*?</script>",
]


def _clean_path(path: str) -> str:
    path = "/" + (path or "").split("?", 1)[0].split("#", 1)[0].strip("/")
    return "/" if path == "/" else path.rstrip("/")


def _strip_html(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`#>]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_RICH_LINK_GAP_RE = re.compile(
    r"\](?:\s|\u200b|\ufeff|&nbsp;|&#(?:32|160);|&#x(?:20|a0);)*\(",
    re.IGNORECASE,
)


def _normalize_rich_links(value: Any) -> str:
    return _RICH_LINK_GAP_RE.sub("](", str(value or ""))


def _strip_rich_text(value: Any) -> str:
    return plain_text(value)


def _limit(value: Any, max_len: int) -> str:
    # Previews and metadata must contain readable link labels, never the raw
    # Markdown notation saved by the editor.
    text = _strip_rich_text(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip(" ,.;:-") + "…"


def _first_text(*values: Any) -> str:
    for value in values:
        text = _strip_rich_text(value)
        if text:
            return text
    return ""


def _absolute_url(value: str | None) -> str:
    value = str(value or DEFAULT_IMAGE).strip()
    if value.startswith(("http://", "https://")):
        return value
    return PUBLIC_SITE_URL + "/" + value.lstrip("/")


def _page_url(path: str) -> str:
    return PUBLIC_SITE_URL + _clean_path(path)


def _canonical_url(value: Any, path: str) -> str:
    """Return a canonical URL only when it belongs to the public site.

    Editors may enter either a relative path or a full URL. External hosts,
    query strings and fragments are intentionally ignored so an accidental
    admin value cannot canonicalize the whole site to another domain.
    """

    default = _page_url(path)
    raw = str(value or "").strip()
    if not raw:
        return default

    if raw.startswith("/"):
        candidate_path = _clean_path(raw)
        if candidate_path != _clean_path(path) and get_http_status_for_path(candidate_path) != 200:
            return default
        return _page_url(candidate_path)

    parsed = urlparse(raw)
    public = urlparse(PUBLIC_SITE_URL)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != public.netloc.lower():
        return default
    candidate_path = _clean_path(parsed.path or "/")
    if candidate_path != _clean_path(path) and get_http_status_for_path(candidate_path) != 200:
        return default
    return _page_url(candidate_path)


def _record_canonical(record: dict[str, Any], path: str) -> str:
    return _canonical_url(
        record.get("seo_canonical_url")
        or record.get("canonical_url")
        or record.get("canonical"),
        path,
    )


def canonical_url_for_path(value: Any, path: str) -> str:
    """Public validator used by admin writes and runtime rendering."""

    return _canonical_url(value, path)


def _settings() -> dict[str, Any]:
    data = load("settings", default={})
    return data if isinstance(data, dict) else {}


REQUIRED_SEO_HUB_FIELDS = ("title", "description", "heading", "intro")
OPTIONAL_SEO_HUB_FIELDS = (
    "catalog_title",
    "cover_image",
    "cover_alt",
    "youtube_title",
    "youtube_url",
    "content_title",
    "content_body",
    "how_to_title",
    "faq_title",
    "seo_image",
)
SEO_HUB_LIST_FIELDS = ("content_sections", "faq_items")
SEO_HUB_TOUR_FIELD = "tour_ids"
EDITABLE_SEO_HUB_FIELDS = (
    *REQUIRED_SEO_HUB_FIELDS,
    *OPTIONAL_SEO_HUB_FIELDS,
    *SEO_HUB_LIST_FIELDS,
    SEO_HUB_TOUR_FIELD,
    "label",
    "custom",
)


def _seo_hub_sections(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "title": str(item.get("title") or "").strip(),
            "text": str(item.get("text") or "").strip(),
        }
        for item in value[:4]
        if isinstance(item, dict)
    ]


def _seo_hub_faq(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "question": str(item.get("question") or "").strip(),
            "answer": str(item.get("answer") or "").strip(),
        }
        for item in value[:8]
        if isinstance(item, dict)
    ]


def _seo_hub_tour_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw_value in value:
        tour_id = str(raw_value or "").strip()
        if tour_id and tour_id not in result:
            result.append(tour_id)
    return result[:500]


def _seo_hub_slug(path: str) -> str:
    return _clean_path(path).removeprefix("/tours/")


def seo_hubs_with_defaults(settings: Any) -> dict[str, dict[str, Any]]:
    settings_dict = settings if isinstance(settings, dict) else {}
    configured = settings_dict.get("seo_hubs")
    configured = configured if isinstance(configured, dict) else {}
    result: dict[str, dict[str, Any]] = {}

    for path, fallback in LANDING_PAGES.items():
        slug = _seo_hub_slug(path)
        selected = configured.get(slug)
        selected = selected if isinstance(selected, dict) else {}
        defaults = {**EMPTY_LANDING_CONTENT, **fallback}
        item: dict[str, Any] = {"path": path}

        for field in REQUIRED_SEO_HUB_FIELDS:
            value = selected.get(field)
            item[field] = (
                str(value).strip()
                if isinstance(value, str) and value.strip()
                else defaults.get(field, "")
            )

        for field in OPTIONAL_SEO_HUB_FIELDS:
            item[field] = (
                str(selected.get(field) or "").strip()
                if field in selected
                else str(defaults.get(field) or "").strip()
            )

        item["content_sections"] = _seo_hub_sections(
            selected["content_sections"]
            if "content_sections" in selected
            else defaults.get("content_sections")
        )
        item["faq_items"] = _seo_hub_faq(
            selected["faq_items"]
            if "faq_items" in selected
            else defaults.get("faq_items")
        )

        # Missing list keeps the existing automatic matching. An empty list
        # is an intentional manual selection with no tours in the hub.
        if isinstance(selected.get(SEO_HUB_TOUR_FIELD), list):
            item[SEO_HUB_TOUR_FIELD] = _seo_hub_tour_ids(
                selected.get(SEO_HUB_TOUR_FIELD)
            )

        if selected.get("content_updated_at"):
            item["content_updated_at"] = selected["content_updated_at"]
        result[slug] = item

    for slug, selected in configured.items():
        if slug in result or not isinstance(selected, dict):
            continue
        if selected.get("custom") is not True:
            continue
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(slug)):
            continue
        if get_by("tours", "slug", slug):
            # A public URL cannot represent a tour and an SEO hub at once.
            continue

        label = str(selected.get("label") or selected.get("heading") or slug).strip()
        item = {
            "custom": True,
            "label": label,
            "path": f"/tours/{slug}",
            "title": str(selected.get("title") or f"{label} | TRAVELSPACE").strip(),
            "description": str(selected.get("description") or "").strip(),
            "heading": str(selected.get("heading") or label).strip(),
            "intro": str(selected.get("intro") or "").strip(),
        }
        for field in OPTIONAL_SEO_HUB_FIELDS:
            item[field] = str(
                selected.get(field)
                if field in selected
                else EMPTY_LANDING_CONTENT.get(field, "")
                or ""
            ).strip()
        item["content_sections"] = _seo_hub_sections(
            selected.get("content_sections")
        )
        item["faq_items"] = _seo_hub_faq(selected.get("faq_items"))
        # Custom hubs are always curated manually. An empty list is valid.
        item[SEO_HUB_TOUR_FIELD] = _seo_hub_tour_ids(
            selected.get(SEO_HUB_TOUR_FIELD)
        )
        if selected.get("content_updated_at"):
            item["content_updated_at"] = selected["content_updated_at"]
        result[slug] = item
    return result


def _landing_pages(settings: Any | None = None) -> dict[str, dict[str, Any]]:
    settings_dict = _settings() if settings is None else settings
    hubs = seo_hubs_with_defaults(settings_dict)
    result: dict[str, dict[str, Any]] = {}
    for slug, hub in hubs.items():
        path = f"/tours/{slug}"
        result[path] = {**LANDING_PAGES.get(path, {}), **hub}
    return result


def settings_with_seo_hub_defaults(settings: Any) -> dict[str, Any]:
    result = dict(settings) if isinstance(settings, dict) else {}
    result["seo_hubs"] = seo_hubs_with_defaults(result)
    return result


def stamp_changed_seo_hubs(
    before: Any,
    after: Any,
    timestamp: str,
) -> dict[str, Any]:
    """Set per-hub lastmod only when an editable field really changes."""

    result = dict(after) if isinstance(after, dict) else {}
    before_hubs = seo_hubs_with_defaults(before)
    after_hubs = seo_hubs_with_defaults(result)

    for slug, item in after_hubs.items():
        previous = before_hubs.get(slug, {})
        changed = any(previous.get(field) != item.get(field) for field in EDITABLE_SEO_HUB_FIELDS)
        if changed:
            item["content_updated_at"] = timestamp
        elif previous.get("content_updated_at"):
            item["content_updated_at"] = previous["content_updated_at"]

    result["seo_hubs"] = after_hubs
    return result


def is_public_tour(tour: Any) -> bool:
    return bool(
        isinstance(tour, dict)
        and tour.get("active", True)
        and tour.get("slug")
    )


def is_listed_tour(tour: Any) -> bool:
    return bool(
        is_public_tour(tour)
        and not tour.get("hidden", False)
        and not tour.get("hide_from_catalog", False)
        and not tour.get("catalog_hidden", False)
        and tour.get("show_in_catalog", True) is not False
        and tour.get("visible", True) is not False
    )


def is_public_article(article: Any) -> bool:
    return bool(isinstance(article, dict) and article.get("active", True) and article.get("slug"))


def is_listed_article(article: Any) -> bool:
    return bool(
        is_public_article(article)
        and not article.get("hidden", False)
        and not article.get("hidden_from_list", False)
        and not article.get("hide_from_list", False)
    )


def is_indexable_tour(tour: Any) -> bool:
    if not is_public_tour(tour) or tour.get("seo_noindex", False):
        return False
    path = f"/tours/{tour['slug']}"
    return _record_canonical(tour, path) == _page_url(path)


def is_indexable_article(article: Any) -> bool:
    if not is_public_article(article) or article.get("seo_noindex", False):
        return False
    path = f"/blog/{article['slug']}"
    return _record_canonical(article, path) == _page_url(path)


def _tour_image(tour: dict[str, Any]) -> str:
    gallery = tour.get("gallery") if isinstance(tour.get("gallery"), list) else []
    return str(
        tour.get("seo_image")
        or tour.get("og_image")
        or tour.get("hero_image")
        or (gallery[0] if gallery else DEFAULT_IMAGE)
    )


def _tour_haystack(tour: dict[str, Any]) -> str:
    return " ".join(
        _strip_html(tour.get(key, "")).lower()
        for key in ("slug", "title", "region_slug", "region_name", "tagline", "short_description")
    )


def _tour_is_air(tour: dict[str, Any]) -> bool:
    haystack = _tour_haystack(tour)
    return tour.get("transport_type") == "air" or any(
        marker in haystack for marker in ("авиа", "перелёт", "перелет", "avia-")
    )


def tours_for_landing(path: str) -> list[dict[str, Any]]:
    config = _landing_pages().get(_clean_path(path), {})
    tours = [tour for tour in list_items("tours") if is_listed_tour(tour)]
    selected = seo_hubs_with_defaults(_settings()).get(
        _seo_hub_slug(path), {}
    )
    manual_tour_ids = selected.get(SEO_HUB_TOUR_FIELD)
    if isinstance(manual_tour_ids, list):
        by_reference: dict[str, dict[str, Any]] = {}
        for tour in tours:
            if tour.get("id"):
                by_reference[str(tour["id"])] = tour
            if tour.get("slug"):
                by_reference[str(tour["slug"])] = tour
        return [
            by_reference[tour_id]
            for tour_id in manual_tour_ids
            if tour_id in by_reference
        ]
    if config.get("kind") == "air":
        return [tour for tour in tours if _tour_is_air(tour)]
    if config.get("kind") == "bus":
        return [tour for tour in tours if not _tour_is_air(tour)]
    keywords = tuple(str(value).lower() for value in config.get("keywords", ()))
    return [tour for tour in tours if any(keyword in _tour_haystack(tour) for keyword in keywords)]


def _static_seo(path: str) -> dict[str, Any]:
    settings = _settings()
    configured = settings.get("seo_pages") if isinstance(settings.get("seo_pages"), dict) else {}
    fallback = STATIC_PAGE_FALLBACKS[path]
    selected: dict[str, Any] = {}
    for page in configured.values():
        if isinstance(page, dict) and _clean_path(page.get("path", "")) == path:
            selected = page
            break
    home_content = home_page_content(settings) if path == "/" else None
    result = {
        "title": selected.get("title") or fallback["title"],
        "description": selected.get("description") or fallback["description"],
        "heading": (
            home_content["h1"]
            if home_content
            else selected.get("visible_heading") or fallback["heading"]
        ),
        "intro": str(selected.get("visible_description") or "").strip(),
        "image": selected.get("image") or settings.get("seo_default_image") or DEFAULT_IMAGE,
        "no_index": bool(selected.get("no_index", False)),
        "type": "website",
    }
    if path == "/":
        faq_entities = []
        for item in _home_faq_items():
            faq_entities.append(
                {
                    "@type": "Question",
                    "name": _strip_rich_text(item.get("question")),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": _strip_rich_text(item.get("answer")),
                    },
                }
            )
        if faq_entities:
            result["structured_data"] = {
                "@type": "FAQPage",
                "mainEntity": faq_entities,
            }
    elif path == "/faq":
        faq_entities = [
            {
                "@type": "Question",
                "name": _strip_rich_text(item.get("question")),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": _strip_rich_text(item.get("answer")),
                },
            }
            for item in list_items("faq")
            if item.get("active", True)
            and _strip_rich_text(item.get("question"))
            and _strip_rich_text(item.get("answer"))
        ]
        if faq_entities:
            result["structured_data"] = {
                "@type": "FAQPage",
                "mainEntity": faq_entities,
            }
    elif path == "/reviews":
        reviews = sort_reviews(
            item
            for item in list_items("reviews")
            if item.get("active", True) and _strip_rich_text(item.get("text"))
        )
        if reviews:
            result["structured_data"] = {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index + 1,
                        "item": {
                            "@type": "Review",
                            "author": {
                                "@type": "Person",
                                "name": _strip_html(review.get("name"))
                                or "Клиент TRAVELSPACE",
                            },
                            "reviewBody": _strip_rich_text(review.get("text")),
                            **(
                                {
                                    "datePublished": _review_date(
                                        review.get("date")
                                    ).date().isoformat()
                                }
                                if _review_date(review.get("date"))
                                else {}
                            ),
                            "reviewRating": {
                                "@type": "Rating",
                                "ratingValue": _review_rating(
                                    review.get("rating")
                                ),
                                "bestRating": 5,
                            },
                            "itemReviewed": {
                                "@type": "TravelAgency",
                                "name": "TRAVELSPACE",
                            },
                        },
                    }
                    for index, review in enumerate(reviews)
                ],
            }
    faq_items = [item for item in selected.get("faq_items", []) if isinstance(item, dict) and _strip_rich_text(item.get("question")) and _strip_rich_text(item.get("answer"))]
    result["page_faq_items"] = faq_items
    result["page_faq_title"] = selected.get("faq_title") or "Частые вопросы"
    if faq_items:
        extra_faq = {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": _strip_rich_text(item["question"]), "acceptedAnswer": {"@type": "Answer", "text": _strip_rich_text(item["answer"])}} for item in faq_items]}
        existing = result.get("structured_data")
        if existing and existing.get("@type") == "FAQPage":
            existing["mainEntity"].extend(extra_faq["mainEntity"])
        else:
            result["structured_data"] = {"@graph": [existing, extra_faq]} if existing else extra_faq
    return result


def _landing_seo(path: str) -> dict[str, Any]:
    config = _landing_pages().get(path, {})
    selected = seo_hubs_with_defaults(_settings()).get(_seo_hub_slug(path), {})
    result = {
        **config,
        **selected,
        "image": selected.get("seo_image") or DEFAULT_IMAGE,
        "no_index": False,
        "type": "website",
    }
    faq_entities = [
        {
            "@type": "Question",
            "name": _strip_rich_text(item.get("question")),
            "acceptedAnswer": {
                "@type": "Answer",
                "text": _strip_rich_text(item.get("answer")),
            },
        }
        for item in selected.get("faq_items", [])
        if isinstance(item, dict)
        and _strip_rich_text(item.get("question"))
        and _strip_rich_text(item.get("answer"))
    ]
    if faq_entities:
        result["structured_data"] = {
            "@type": "FAQPage",
            "mainEntity": faq_entities,
        }
    return result


def _not_found(kind: str = "Страница") -> dict[str, Any]:
    heading = f"{kind} не найден" if kind == "Тур" else f"{kind} не найдена"
    return {
        "title": f"{heading} | TRAVELSPACE",
        "description": f"{heading}. Перейдите в каталог актуальных туров TRAVELSPACE.",
        "heading": heading,
        "image": DEFAULT_IMAGE,
        "no_index": True,
        "type": "website",
    }


def _tour_seo(slug: str, path: str) -> dict[str, Any]:
    tour = get_by("tours", "slug", slug)
    if not is_public_tour(tour):
        return _not_found("Тур")
    if tour.get("hotels") or any(chain.get("hotels") for chain in tour.get("chains") or []):
        tour = decorate_tour(tour)
    description = _first_text(
        tour.get("seo_description"), tour.get("short_description"), tour.get("tagline"),
        tour.get("description"), f"{tour.get('title', 'Тур')}: программа, даты и стоимость поездки."
    )
    canonical_url = _record_canonical(tour, path)
    structured = {
        "@type": "TouristTrip",
        "name": tour.get("title"),
        "description": _limit(description, 220),
        "url": canonical_url,
        "image": _absolute_url(_tour_image(tour)),
        "touristType": "Групповой тур",
        "provider": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
    }
    return {
        "title": _first_text(tour.get("seo_title"), f"{tour.get('title', 'Тур')} | TRAVELSPACE"),
        "description": description,
        "heading": tour.get("title"),
        "image": _tour_image(tour),
        "canonical_url": canonical_url,
        "no_index": bool(tour.get("seo_noindex", False)),
        "no_follow": bool(tour.get("seo_nofollow", False)),
        "type": "article",
        "structured_data": structured,
        "record": tour,
    }


def _hotel_seo(slug: str, path: str) -> dict[str, Any]:
    hotel = next((h for h in hotel_records(list_items("tours"), public=True) if h["slug"] == slug), None)
    if not hotel:
        return {**_not_found(), "heading": "Отель не найден", "title": "Отель не найден | TRAVELSPACE"}
    description = _first_text(hotel.get("seo_description"), hotel.get("short_description"), hotel.get("description"), f'{hotel["name"]}: номера, питание и расположение.')
    image = hotel.get("seo_image") or hotel.get("image") or next(iter(hotel.get("images") or []), DEFAULT_IMAGE)
    canonical = _record_canonical(hotel, path)
    return {
        "title": hotel.get("seo_title") or f'{hotel["name"]} | TRAVELSPACE',
        "heading": hotel["name"], "description": description, "image": image,
        "canonical_url": canonical, "no_index": hotel.get("seo_noindex", False),
        "no_follow": hotel.get("seo_nofollow", False), "type": "website", "record": hotel,
        "structured_data": {"@type": "Hotel", "name": hotel["name"], "description": _limit(description, 220),
                            "url": canonical, "image": _absolute_url(image), "address": hotel.get("address") or hotel.get("location") or None},
    }


def _article_seo(slug: str, path: str) -> dict[str, Any]:
    article = get_by("articles", "slug", slug)
    if not is_public_article(article):
        return _not_found("Статья")
    description = _first_text(article.get("seo_description"), article.get("excerpt"), article.get("content"), DEFAULT_DESCRIPTION)
    canonical_url = _record_canonical(article, path)
    structured: dict[str, Any] = {
        "@type": "Article",
        "headline": article.get("seo_h1") or article.get("title"),
        "description": _limit(description, 220),
        "mainEntityOfPage": canonical_url,
        "image": _absolute_url(article.get("seo_image") or article.get("cover") or DEFAULT_IMAGE),
        "author": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
        "publisher": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
    }
    if article.get("published_at"):
        structured["datePublished"] = article["published_at"]
    if article.get("seo_lastmod") or article.get("updated_at"):
        structured["dateModified"] = article.get("seo_lastmod") or article["updated_at"]
    return {
        "title": _first_text(article.get("seo_title"), f"{article.get('title', 'Статья')} | TRAVELSPACE"),
        "description": description,
        "heading": article.get("seo_h1") or article.get("title"),
        "image": article.get("seo_image") or article.get("cover") or DEFAULT_IMAGE,
        "canonical_url": canonical_url,
        "no_index": bool(article.get("seo_noindex", False)),
        "no_follow": bool(article.get("seo_nofollow", False)),
        "type": "article",
        "structured_data": structured,
        "record": article,
    }


def get_redirect_target(path: str) -> str | None:
    path = _clean_path(path)
    if path in BUILT_IN_REDIRECTS:
        return BUILT_IN_REDIRECTS[path]
    redirects = load("redirects", default=[])
    if not isinstance(redirects, list):
        return None
    for item in redirects:
        if isinstance(item, dict) and _clean_path(item.get("from", "")) == path:
            target = item.get("to")
            return str(target) if target else None
    return None


def get_http_status_for_path(path: str) -> int:
    path = _clean_path(path)
    if path.startswith("/admin"):
        return 200
    if path in STATIC_PAGE_FALLBACKS or path in _landing_pages() or path in SERVICE_PAGES:
        return 200
    if path.startswith("/tours/"):
        slug = path.removeprefix("/tours/")
        return 200 if "/" not in slug and is_public_tour(get_by("tours", "slug", slug)) else 404
    if path.startswith("/blog/"):
        slug = path.removeprefix("/blog/")
        return 200 if "/" not in slug and is_public_article(get_by("articles", "slug", slug)) else 404
    if path.startswith("/hotels/"):
        slug = path.removeprefix("/hotels/")
        return 200 if any(h["slug"] == slug for h in hotel_records(list_items("tours"), public=True)) else 404
    return 404


def get_seo_for_path(path: str) -> dict[str, Any]:
    path = _clean_path(path)
    if path.startswith(("/admin", "/api")):
        return {**_not_found("Страница"), "title": "TRAVELSPACE"}
    if path in SERVICE_PAGES:
        headings = {"/thanks": "Заявка отправлена", "/links": "TRAVELSPACE в социальных сетях"}
        return {
            "title": f"{headings[path]} | TRAVELSPACE",
            "description": DEFAULT_DESCRIPTION,
            "heading": headings[path],
            "image": DEFAULT_IMAGE,
            "no_index": True,
            "type": "website",
        }
    if path in _landing_pages():
        return _landing_seo(path)
    if path.startswith("/tours/"):
        return _tour_seo(path.removeprefix("/tours/").split("/", 1)[0], path)
    if path.startswith("/blog/"):
        return _article_seo(path.removeprefix("/blog/").split("/", 1)[0], path)
    if path.startswith("/hotels/"):
        return _hotel_seo(path.removeprefix("/hotels/"), path)
    if path in STATIC_PAGE_FALLBACKS:
        return _static_seo(path)
    return _not_found()


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_json(item) for key, item in value.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_safe_json(item) for item in value if item not in (None, "", [], {})]
    return value


def _breadcrumb_items(path: str, seo: dict[str, Any]) -> list[dict[str, Any]]:
    items = [{"@type": "ListItem", "position": 1, "name": "Главная", "item": PUBLIC_SITE_URL + "/"}]
    if path != "/":
        if path.startswith("/tours/"):
            items.append({"@type": "ListItem", "position": 2, "name": "Туры", "item": _page_url("/tours")})
        elif path.startswith("/blog/"):
            items.append({"@type": "ListItem", "position": 2, "name": "Блог", "item": _page_url("/blog")})
        elif path.startswith("/hotels/") and seo.get("record"):
            hotel = seo["record"]
            items.append({"@type": "ListItem", "position": 2, "name": hotel["tour_title"], "item": _page_url("/tours/" + hotel["tour_slug"])})
        items.append({
            "@type": "ListItem",
            "position": len(items) + 1,
            "name": _strip_html(seo.get("heading") or seo.get("title")),
            "item": _page_url(path),
        })
    return items


def _structured_graph(path: str, seo: dict[str, Any]) -> dict[str, Any]:
    settings = _settings()
    canonical_url = seo.get("canonical_url") or _page_url(path)
    organization: dict[str, Any] = {
        "@type": ["Organization", "TravelAgency"],
        "@id": f"{PUBLIC_SITE_URL}/#organization",
        "name": settings.get("company_short") or SITE_NAME,
        "url": PUBLIC_SITE_URL + "/",
        "logo": _absolute_url(settings.get("seo_default_image") or DEFAULT_IMAGE),
        "image": _absolute_url(settings.get("seo_default_image") or DEFAULT_IMAGE),
        "telephone": settings.get("phone"),
        "email": settings.get("email"),
        "address": settings.get("address"),
    }
    graph: list[dict[str, Any]] = [
        organization,
        {
            "@type": "WebSite",
            "@id": f"{PUBLIC_SITE_URL}/#website",
            "url": PUBLIC_SITE_URL + "/",
            "name": SITE_NAME,
            "publisher": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
            "inLanguage": "ru-BY",
        },
        {
            "@type": "WebPage",
            "@id": canonical_url + "#webpage",
            "url": canonical_url,
            "name": _strip_html(seo.get("title")),
            "description": _limit(seo.get("description"), 220),
            "isPartOf": {"@id": f"{PUBLIC_SITE_URL}/#website"},
            "inLanguage": "ru-BY",
        },
    ]
    breadcrumbs = _breadcrumb_items(path, seo)
    if len(breadcrumbs) > 1:
        graph.append({
            "@type": "BreadcrumbList",
            "@id": _page_url(path) + "#breadcrumb",
            "itemListElement": breadcrumbs,
        })
    if seo.get("structured_data"):
        structured = seo["structured_data"]
        graph.extend(structured.get("@graph", [{key: value for key, value in structured.items() if key != "@context"}]))
    return _safe_json({"@context": "https://schema.org", "@graph": graph})


def _render_meta_block(path: str, seo: dict[str, Any]) -> str:
    title = _limit(_first_text(seo.get("title"), DEFAULT_TITLE), 80)
    description = _limit(_first_text(seo.get("description"), DEFAULT_DESCRIPTION), 180)
    image = _absolute_url(seo.get("image"))
    url = seo.get("canonical_url") or _page_url(path)
    robots = ", ".join(
        (
            "noindex" if seo.get("no_index") else "index",
            "nofollow" if seo.get("no_follow") else "follow",
        )
    )
    og_type = seo.get("type") or "website"
    attr = ' data-rh="true"'
    lines = [
        f"<title{attr}>{escape(title)}</title>",
        f'<meta{attr} name="description" content="{escape(description, quote=True)}" />',
        f'<meta{attr} name="robots" content="{robots}" />',
        f'<link{attr} rel="canonical" href="{escape(url, quote=True)}" />',
        f'<meta{attr} property="og:type" content="{escape(og_type, quote=True)}" />',
        f'<meta{attr} property="og:site_name" content="{SITE_NAME}" />',
        f'<meta{attr} property="og:locale" content="ru_BY" />',
        f'<meta{attr} property="og:title" content="{escape(title, quote=True)}" />',
        f'<meta{attr} property="og:description" content="{escape(description, quote=True)}" />',
        f'<meta{attr} property="og:url" content="{escape(url, quote=True)}" />',
        f'<meta{attr} property="og:image" content="{escape(image, quote=True)}" />',
        f'<meta{attr} property="og:image:secure_url" content="{escape(image, quote=True)}" />',
        f'<meta{attr} name="twitter:card" content="summary_large_image" />',
        f'<meta{attr} name="twitter:title" content="{escape(title, quote=True)}" />',
        f'<meta{attr} name="twitter:description" content="{escape(description, quote=True)}" />',
        f'<meta{attr} name="twitter:image" content="{escape(image, quote=True)}" />',
        f'<script{attr} type="application/ld+json">{_script_json(_structured_graph(path, seo))}</script>',
    ]
    return "\n    " + "\n    ".join(lines) + "\n"


def _flatten_text(value: Any, preserve_rich: bool = False) -> list[str]:
    if isinstance(value, str):
        clean = re.sub(r"<[^>]+>", " ", value).strip() if preserve_rich else _strip_html(value)
        return [clean] if clean else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_text(item, preserve_rich))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if key not in {"id", "image", "icon", "map_embed", "slug"}:
                result.extend(_flatten_text(item, preserve_rich))
        return result
    return []


def _safe_rich_href(value: Any) -> str | None:
    href = str(value or "").strip()
    if href.startswith("/") and not href.startswith("//"):
        return href
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return href
    return None


def _render_rich_inline(value: Any) -> str:
    return render_inline(value)


def _render_rich_paragraphs(value: Any, limit: int | None = None) -> str:
    if not isinstance(value, str):
        return _render_paragraphs(value, limit=limit)
    value = _normalize_rich_links(value).replace("\r\n", "\n")
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", value)
        if block.strip()
    ]
    selected = blocks if limit is None else blocks[:limit]
    return "".join(
        "<p>"
        + "<br />".join(_render_rich_inline(line) for line in block.split("\n"))
        + "</p>"
        for block in selected
    )


def _render_paragraphs(value: Any, limit: int | None = 8, semantic_headings: bool = False) -> str:
    chunks: list[str] = []
    if isinstance(value, str):
        normalized = _normalize_rich_links(value)
        chunks = [part.strip() for part in re.split(r"\n\s*\n|\r?\n", normalized) if part.strip()]
    else:
        chunks = _flatten_text(value, preserve_rich=True)
    rendered: list[str] = []
    selected_chunks = chunks if limit is None else chunks[:limit]
    for chunk in selected_chunks:
        clean = re.sub(r"<[^>]+>", "", str(chunk)).strip()
        if semantic_headings and clean.startswith("## "):
            rendered.append(f"<h2>{_render_rich_inline(clean[3:])}</h2>")
            continue
        semantic = re.match(r"^(\d+)\.\s+(.+?[.!?])(?:\s+(.+))?$", clean) if semantic_headings else None
        if semantic:
            rendered.append(f"<h2>{_render_rich_inline(semantic.group(1) + '. ' + semantic.group(2))}</h2>")
            if semantic.group(3):
                rendered.append(f"<p>{_render_rich_inline(semantic.group(3))}</p>")
        else:
            rendered.append(f"<p>{_render_rich_inline(clean)}</p>")
    return "".join(rendered)


def _link(path: str, label: Any) -> str:
    return f'<a href="{escape(_page_url(path), quote=True)}">{escape(_strip_html(label))}</a>'


def _content_order(item: dict[str, Any]) -> tuple[float, str]:
    try:
        order = float(item.get("order", 9999))
    except (TypeError, ValueError):
        order = 9999
    return order, str(item.get("question") or item.get("title") or "")


def _review_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], pattern)
        except ValueError:
            continue
    return None


def sort_reviews(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest dated reviews first; undated legacy entries always come last."""

    def key(item: dict[str, Any]) -> tuple[int, float, tuple[float, str]]:
        published = _review_date(item.get("date"))
        return (
            0 if published else 1,
            -published.timestamp() if published else 0,
            _content_order(item),
        )

    return sorted(items, key=key)


def _review_rating(value: Any) -> int:
    try:
        return max(1, min(5, int(value or 5)))
    except (TypeError, ValueError):
        return 5


def _home_faq_items() -> list[dict[str, Any]]:
    items = [item for item in list_items("faq") if is_home_faq(item)]
    return sorted(items, key=_content_order)


def _render_list(value: Any) -> str:
    items = _flatten_text(value, preserve_rich=True)
    return "<ul>" + "".join(f"<li>{_render_rich_inline(item)}</li>" for item in items) + "</ul>" if items else ""


def _render_tour_gallery(tour: dict[str, Any]) -> str:
    images = tour.get("gallery") if isinstance(tour.get("gallery"), list) else []
    alts = tour.get("gallery_alts") if isinstance(tour.get("gallery_alts"), list) else []
    figures = []
    for index, image in enumerate(images):
        if not image:
            continue
        alt = _strip_html(alts[index] if index < len(alts) else "") or _strip_html(tour.get("title"))
        figures.append(
            '<figure><img loading="lazy" width="1200" height="750" '
            f'src="{escape(_absolute_url(image), quote=True)}" alt="{escape(alt, quote=True)}" /></figure>'
        )
    return "".join(figures)


def _render_tour_videos(tour: dict[str, Any]) -> str:
    videos = tour.get("videos") if isinstance(tour.get("videos"), list) else []
    rendered: list[str] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        url = str(video.get("url") or video.get("video_url") or "").strip()
        parsed = urlparse(url)
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not (
            hostname == "youtu.be"
            or hostname == "youtube.com"
            or hostname.endswith(".youtube.com")
        ):
            continue
        title = _strip_html(video.get("title")) or "Видео о туре"
        description = _render_rich_paragraphs(video.get("description"))
        rendered.append(
            "<li>"
            f'<a href="{escape(url, quote=True)}">{escape(title)}</a>'
            + description
            + "</li>"
        )
    return "<ul>" + "".join(rendered) + "</ul>" if rendered else ""


def _render_related_tours(tour: dict[str, Any]) -> str:
    slugs = (
        tour.get("related_tour_slugs")
        if isinstance(tour.get("related_tour_slugs"), list)
        else [tour.get("related_tour_slug")]
    )
    rendered: list[str] = []
    for slug in slugs:
        related = get_by("tours", "slug", str(slug))
        if not is_listed_tour(related) or related.get("slug") == tour.get("slug"):
            continue
        rendered.append(
            f"<li>{_link('/tours/' + related['slug'], related.get('title'))}</li>"
        )
    return "<ul>" + "".join(rendered) + "</ul>" if rendered else ""


_TOUR_ANCHOR_TRANSLITERATION = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }
)


def _clean_tour_anchor(value: Any) -> str:
    source = str(value or "").strip().lower()
    if "#" in source:
        source = source.rsplit("#", 1)[-1]
    source = source.translate(_TOUR_ANCHOR_TRANSLITERATION)
    source = re.sub(r"[^a-z0-9]+", "-", source).strip("-")
    return source[:80]


def _tour_anchor_markers(
    tour: dict[str, Any], key: str, default_anchor: str = ""
) -> str:
    anchors = tour.get("section_anchors")
    anchors = anchors if isinstance(anchors, dict) else {}
    custom = _clean_tour_anchor(anchors.get(key))
    default_value = _clean_tour_anchor(default_anchor)
    values = list(dict.fromkeys(item for item in (default_value, custom) if item))
    return "".join(
        f'<span id="{escape(anchor, quote=True)}" data-tour-anchor="true"></span>'
        for anchor in values
    )


def _render_tour_program(program: Any) -> str:
    if not isinstance(program, list):
        return ""
    result: list[str] = []
    for index, day in enumerate(program):
        if not isinstance(day, dict):
            continue
        day_number = _strip_html(day.get("day") or index + 1)
        day_title = _strip_html(day.get("title"))
        heading = f"День {day_number}" + (f" — {day_title}" if day_title else "")
        anchor = _clean_tour_anchor(day.get("anchor"))
        anchor_attr = f' id="{escape(anchor, quote=True)}"' if anchor else ""
        result.append(f"<section{anchor_attr}><h3>{escape(heading)}</h3>")
        result.append(_render_paragraphs(day.get("description"), limit=None))
        result.append(_render_paragraphs(day.get("notes"), limit=None))
        result.append("</section>")
    return "".join(result)


def _render_tour_faq(faq: Any) -> str:
    if not isinstance(faq, list):
        return ""
    result: list[str] = []
    for item in faq:
        if not isinstance(item, dict):
            continue
        question = _strip_html(item.get("question"))
        answer = _render_paragraphs(item.get("answer"), limit=None)
        if question and answer:
            result.append(f"<section><h3>{escape(question)}</h3>{answer}</section>")
    return "".join(result)


def _tour_dates(tour: dict[str, Any]) -> list[dict[str, Any]]:
    dates: list[dict[str, Any]] = []
    if isinstance(tour.get("dates"), list):
        dates.extend(item for item in tour["dates"] if isinstance(item, dict))
    if isinstance(tour.get("chains"), list):
        for chain in tour["chains"]:
            if not isinstance(chain, dict) or chain.get("active", True) is False:
                continue
            if isinstance(chain.get("dates"), list):
                dates.extend(item for item in chain["dates"] if isinstance(item, dict))
    unique: dict[str, dict[str, Any]] = {}
    for item in dates:
        if item.get("status") == "hidden":
            continue
        key = str(item.get("id") or f"{item.get('start')}|{item.get('end')}|{item.get('price')}")
        unique.setdefault(key, item)
    return list(unique.values())


def _render_tour_dates_and_prices(tour: dict[str, Any]) -> str:
    result: list[str] = []
    base_price = tour.get("price_from")
    if base_price not in (None, ""):
        price_type = _strip_html(tour.get("price_type") or "от")
        currency = _strip_html(tour.get("currency") or "BYN")
        result.append(f"<p>Стоимость {escape(price_type)} {escape(str(base_price))} {escape(currency)}</p>")
    date_items = []
    for item in _tour_dates(tour):
        start = _strip_html(item.get("start"))
        end = _strip_html(item.get("end"))
        label = start + (f" — {end}" if end and end != start else "")
        price = item.get("promotion_price") if item.get("promotion_active") and item.get("promotion_price") not in (None, "") else item.get("price")
        currency = item.get("promotion_currency") if item.get("promotion_active") else item.get("currency")
        if price in (None, ""):
            price = base_price
            currency = currency or tour.get("currency")
        if price not in (None, ""):
            label += f": {price} {currency or 'BYN'}"
        if item.get("comment"):
            label += " — " + str(item["comment"])
        if label:
            special_active = (
                item.get("special_active") is True
                or item.get("specialActive") is True
            )
            special_label = _strip_html(
                item.get("special_label") or item.get("specialLabel")
            )[:80]
            special_slug = _strip_html(
                item.get("special_tour_slug") or item.get("specialTourSlug")
            ).strip().strip("/")
            special_cta = _strip_html(
                item.get("special_cta_label") or item.get("specialCtaLabel")
            )[:80]
            rendered = escape(label)
            if special_active:
                rendered = (
                    f"<strong>{escape(special_label or 'Особая дата')}</strong> — "
                    + rendered
                )
                if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", special_slug):
                    rendered += " — " + _link(
                        f"/tours/{special_slug}",
                        special_cta or "Смотреть специальную программу",
                    )
            date_items.append(f"<li>{rendered}</li>")
    if date_items:
        result.append("<ul>" + "".join(date_items) + "</ul>")
    return "".join(result)


def _tour_list(tours: Iterable[dict[str, Any]]) -> str:
    items = []
    for tour in tours:
        description = tour.get("short_description") or tour.get("tagline") or tour.get("description")
        items.append(
            "<li>"
            + "<h3>"
            + _link(f"/tours/{tour['slug']}", tour.get("title") or "Тур")
            + "</h3>"
            + (f"<p>{escape(_limit(description, 240))}</p>" if description else "")
            + "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>Новые даты и маршруты скоро появятся в каталоге.</p>"


def _global_navigation() -> str:
    links = [
        ("/", "Главная"),
        ("/tours", "Все туры"),
        ("/promotions", "Акции"),
        ("/blog", "Блог"),
        ("/reviews", "Отзывы"),
        ("/about", "О компании"),
        ("/agencies", "Агентствам"),
        ("/payment", "Оплата"),
        ("/faq", "Частые вопросы"),
        ("/contacts", "Контакты"),
        ("/legal", "Документы"),
    ]
    return '<nav aria-label="Основная навигация">' + " ".join(_link(path, label) for path, label in links) + "</nav>"


def _render_homepage_sections() -> str:
    settings = _settings()
    content = home_page_content(settings)
    parts = [
        f"<h2>{escape(content['intro_title'])}</h2>",
        _render_rich_paragraphs(content["intro_text"]),
        f"<h2>{escape(content['tours_title'])}</h2>",
        _tour_list(tour for tour in list_items("tours") if is_listed_tour(tour) and not _tour_is_air(tour)),
        f"<h2>{escape(content['directions_title'])}</h2>",
    ]

    for section in content["directions_sections"]:
        title = _strip_html(section.get("title"))
        body = _render_rich_paragraphs(section.get("text"))
        if not title and not body:
            continue
        parts.append("<section>")
        if title:
            parts.append(f"<h3>{escape(title)}</h3>")
        if body:
            parts.append(body)
        link_label = _strip_html(section.get("link_label"))
        link_url = _safe_rich_href(section.get("link_url"))
        if link_label and link_url:
            parts.append(
                f'<p><a href="{escape(link_url, quote=True)}">'
                f"{escape(link_label)}</a></p>"
            )
        parts.append("</section>")

    benefits = home_benefits_content(settings)
    benefits_heading = _strip_html(benefits.get("overline")) or "Почему едут именно с нами"
    benefits_subtitle = _strip_html(benefits.get("title")) or "Заботимся о каждой детали поездки"
    parts.append(f"<h2>{escape(benefits_heading)}</h2>")
    if benefits_subtitle and benefits_subtitle != benefits_heading:
        parts.append(f"<p>{escape(benefits_subtitle)}</p>")
    benefit_items = benefits.get("items") if isinstance(benefits.get("items"), list) else []
    if benefit_items:
        parts.append("<ul>")
        for item in benefit_items:
            if not isinstance(item, dict):
                continue
            title = _strip_html(item.get("title"))
            description = _render_rich_inline(item.get("desc"))
            if title or description:
                parts.append(
                    "<li>"
                    + (f"<h3>{escape(title)}</h3>" if title else "")
                    + (f"<p>{description}</p>" if description else "")
                    + "</li>"
                )
        parts.append("</ul>")

    reviews = sort_reviews(
        item for item in list_items("reviews") if item.get("active", True)
    )
    if reviews:
        parts.append(f"<h2>{escape(content['reviews_title'])}</h2>")
        if content.get("reviews_subtitle"):
            parts.append(
                f"<p>{escape(content['reviews_subtitle'])}</p>"
            )
        parts.append("<ul>")
        for review in reviews[:4]:
            author = _strip_html(review.get("name")) or "Турист"
            text = _strip_html(review.get("text"))
            parts.append(
                f"<li><h3>{escape(author)}</h3>"
                + (f"<p>{escape(_limit(text, 500))}</p>" if text else "")
                + "</li>"
            )
        parts.append("</ul>")

    promotions = [item for item in list_items("promotions") if item.get("active", True)]
    if promotions:
        if content.get("promotions_overline"):
            parts.append(
                f"<p>{escape(content['promotions_overline'])}</p>"
            )
        parts.append(f"<h2>{escape(content['promotions_title'])}</h2><ul>")
        for promotion in promotions[:3]:
            title = _strip_html(promotion.get("title"))
            description = _strip_html(promotion.get("description"))
            parts.append(
                "<li>"
                + (f"<h3>{escape(title)}</h3>" if title else "")
                + (f"<p>{escape(_limit(description, 500))}</p>" if description else "")
                + "</li>"
            )
        parts.append("</ul>")

    faq_items = _home_faq_items()
    if faq_items:
        parts.append(f"<h2>{escape(content['faq_title'])}</h2>")
        for item in faq_items:
            parts.append(
                f"<section><h3>{escape(_strip_html(item.get('question')))}</h3>"
                f"{_render_rich_paragraphs(item.get('answer'))}</section>"
            )

    return "".join(parts)


def _render_static_page_content(path: str) -> str:
    """Render useful non-JavaScript content for every indexable static page."""

    settings = _settings()
    if path == "/about":
        return (
            "<section><h2>Делаем путешествия простыми</h2>"
            "<p>TRAVELSPACE - туроператор автобусных туров из Минска. Мы сами разрабатываем маршруты, проходим их и сопровождаем группы в дороге.</p>"
            "<p>Хороший тур для нас - это спокойное знакомство с местом, заботливый гид и понятная программа без сюрпризов.</p>"
            "<h2>Во что мы верим</h2><ul>"
            "<li><h3>Забота важнее галочек</h3><p>Лучше пройти меньше точек, чем устать и не запомнить ни одной.</p></li>"
            "<li><h3>Сначала идём сами</h3><p>Все маршруты протестированы лично - мы знаем их особенности.</p></li>"
            "<li><h3>Прозрачные цены</h3><p>Состав стоимости и возможные доплаты указаны на странице каждого тура.</p></li>"
            "</ul></section>"
        )

    if path == "/contacts":
        values = []
        header_phones = settings.get("header_phones")
        if isinstance(header_phones, list):
            for item in header_phones:
                if isinstance(item, dict):
                    phone = _strip_html(item.get("phone"))
                    label = _strip_html(item.get("label"))
                    if phone:
                        values.append(f"<li>{escape(label + ': ' if label else '')}{escape(phone)}</li>")
        if not values and settings.get("phone"):
            values.append(f"<li>Телефон: {escape(_strip_html(settings.get('phone')))}</li>")
        for label, key in (
            ("Email", "email"),
            ("Адрес офиса", "address"),
            ("Режим работы", "work_hours"),
        ):
            value = _strip_html(settings.get(key))
            if value:
                values.append(f"<li>{escape(label)}: {escape(value)}</li>")
        return (
            "<section><h2>Как связаться с TRAVELSPACE</h2>"
            + ("<ul>" + "".join(values) + "</ul>" if values else "")
            + "<p>Позвоните, напишите или оставьте заявку на сайте. Менеджер поможет подобрать тур, уточнит даты, наличие мест и итоговую стоимость.</p>"
            "</section>"
        )

    if path == "/faq":
        items = [item for item in list_items("faq") if item.get("active", True)]
        items.sort(key=_content_order)
        parts = [
            "<p>Ответы на вопросы о бронировании, оплате, документах и поездках с TRAVELSPACE.</p>"
        ]
        current_category = None
        for item in items:
            category = _strip_html(item.get("category")) or "Общее"
            if category != current_category:
                parts.append(f"<h2>{escape(category)}</h2>")
                current_category = category
            question = _strip_html(item.get("question"))
            answer = _render_rich_paragraphs(item.get("answer"))
            if question and answer:
                parts.append(f"<section><h3>{escape(question)}</h3>{answer}</section>")
        return "".join(parts)

    if path == "/promotions":
        items = [item for item in list_items("promotions") if item.get("active", True)]
        parts = ["<p>Действующие скидки и специальные условия на поездки TRAVELSPACE.</p>"]
        for item in items:
            title = _strip_html(item.get("title"))
            description = _render_rich_paragraphs(item.get("description"))
            valid_until = _strip_html(item.get("valid_until"))
            related = item.get("related_tour_slugs") or [item.get("related_tour_slug")]
            links = []
            for slug in related:
                tour = get_by("tours", "slug", slug) if slug else None
                if is_listed_tour(tour):
                    links.append(_link(f"/tours/{slug}", tour.get("title") or "Подробнее о туре"))
            parts.append("<article>")
            if title:
                parts.append(f"<h2>{escape(title)}</h2>")
            if description:
                parts.append(description)
            if valid_until:
                parts.append(f"<p>Действует до {escape(valid_until)}</p>")
            if links:
                parts.append("<p>" + " ".join(links) + "</p>")
            parts.append("</article>")
        return "".join(parts)

    if path == "/reviews":
        items = sort_reviews(
            item for item in list_items("reviews") if item.get("active", True)
        )
        parts = ["<p>Впечатления туристов о маршрутах и поездках с TRAVELSPACE.</p>"]
        for item in items:
            author = _strip_html(item.get("name")) or "Турист TRAVELSPACE"
            tour_name = _strip_html(item.get("tour_name"))
            text = _render_rich_paragraphs(item.get("text"))
            if text:
                parts.append(
                    "<article>"
                    f"<h2>{escape(author)}</h2>"
                    + (f"<p>{escape(tour_name)}</p>" if tour_name else "")
                    + text
                    + "</article>"
                )
        return "".join(parts)

    if path == "/agencies":
        return (
            "<section><h2>Работаем с турагентствами по всей Беларуси</h2>"
            "<p>Сотрудничаем на прозрачных условиях: фиксированные комиссии, оперативные подтверждения, готовые рекламные материалы и поддержка менеджера на каждом этапе.</p>"
            "<ul>"
            "<li><h3>Гарантированные блок-места</h3><p>Закрепляем места под агентство на пиковые даты.</p></li>"
            "<li><h3>Профильный менеджер</h3><p>Один специалист ведёт группы без передачи между отделами.</p></li>"
            "<li><h3>Готовые материалы</h3><p>Предоставляем программы, фотографии, описания и презентации.</p></li>"
            "<li><h3>Официальный договор</h3><p>Работаем по договору и предоставляем закрывающие документы.</p></li>"
            "</ul><h2>Заявка от агентства</h2><p>Оставьте заявку, и персональный менеджер свяжется в течение рабочего дня.</p></section>"
        )

    if path == "/payment":
        return (
            "<section><p>Бронирование и оплата происходят после общения с менеджером и подписания договора.</p>"
            "<h2>Как оформить и оплатить тур</h2><ol>"
            "<li><h3>Оставьте заявку</h3><p>На сайте, в мессенджере или по телефону.</p></li>"
            "<li><h3>Обсудите поездку с менеджером</h3><p>Уточните тур, даты, количество туристов и особые пожелания.</p></li>"
            "<li><h3>Заключите договор</h3><p>После подписания вы получите номер договора для оплаты.</p></li>"
            "<li><h3>Оплатите через ЕРИП</h3><p>В интернет-банкинге или мобильном приложении выберите ЕРИП, найдите TRAVELSPACE, введите номер договора и подтвердите платёж.</p></li>"
            "</ol><p>Если возникли вопросы, свяжитесь с менеджером на странице "
            + _link("/contacts", "контактов")
            + ".</p></section>"
        )

    if path == "/legal":
        return (
            "<section><h2>Политика конфиденциальности</h2>"
            "<p>Мы собираем только данные, необходимые для обработки заявки: имя, телефон, выбранное направление и комментарий. Они используются для связи и заключения договора и не передаются третьим лицам для нерелевантных рассылок.</p>"
            "<p>Запросить удаление данных можно по электронной почте компании.</p>"
            "<h2>Публичный договор</h2><p>Условия туристических услуг, порядок оплаты, отмены тура и возврата средств описаны в публичном договоре.</p>"
            '<p><a href="/public-contract.pdf">Открыть публичный договор</a></p>'
            "<h2>Согласие на обработку персональных данных</h2><p>Отправляя заявку, посетитель подтверждает согласие на обработку указанных данных для оказания услуг и связи.</p>"
            "<h2>Реквизиты компании</h2><p>ООО «Пространство Путешествий». УНП 193738609. Регистрация в реестре субъектов туристической деятельности Республики Беларусь, №1310.</p></section>"
        )

    return ""


def _render_seo_hub_content(seo: dict[str, Any]) -> str:
    title = _strip_html(seo.get("content_title"))
    body = _render_rich_paragraphs(seo.get("content_body"))
    sections = seo.get("content_sections")
    sections = sections if isinstance(sections, list) else []

    rendered_sections: list[str] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        section_title = _strip_html(item.get("title"))
        section_body = _render_rich_paragraphs(item.get("text"))
        if not section_title or not section_body:
            continue
        rendered_sections.append(
            "<section>"
            + (f"<h3>{escape(section_title)}</h3>" if section_title else "")
            + section_body
            + "</section>"
        )

    if not title or not (body or rendered_sections):
        return ""
    return (
        "<section>"
        + (f"<h2>{escape(title)}</h2>" if title else "")
        + body
        + "".join(rendered_sections)
        + "</section>"
    )


def _render_seo_hub_faq(seo: dict[str, Any]) -> str:
    title = _strip_html(seo.get("faq_title")) or "Частые вопросы о турах"
    faq_items = seo.get("faq_items")
    faq_items = faq_items if isinstance(faq_items, list) else []
    rendered: list[str] = []

    for item in faq_items:
        if not isinstance(item, dict):
            continue
        question = _strip_html(item.get("question"))
        answer = _render_rich_paragraphs(item.get("answer"))
        if question and answer:
            rendered.append(
                f"<section><h3>{escape(question)}</h3>{answer}</section>"
            )

    if not rendered:
        return ""
    return (
        "<section>"
        + f"<h2>{escape(title)}</h2>"
        + "".join(rendered)
        + "</section>"
    )


def _render_article_body(article: dict[str, Any]) -> str:
    parts = []
    for block in article_blocks(article):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(_render_paragraphs(block.get("text"), limit=None, semantic_headings=True))
        elif block.get("type") == "image":
            src = str(block.get("src") or "").strip()
            if not src or not (src.startswith("/") and not src.startswith("//") or src.startswith(("https://", "http://"))):
                continue
            alt = str(block.get("alt") or article.get("seo_h1") or article.get("title") or "")
            parts.append(f'<figure><img src="{escape(_absolute_url(src), quote=True)}" alt="{escape(alt, quote=True)}" width="1200" height="750" loading="lazy"></figure>')
    return "".join(parts)


def _build_asset(name: str) -> str:
    """Resolve the current build's hashed asset without guessing filenames."""
    try:
        manifest = json.loads((FRONTEND_BUILD_DIR / "asset-manifest.json").read_text(encoding="utf-8"))
        return manifest.get("files", {}).get(name, "")
    except (OSError, ValueError):
        return ""


def _home_first_screen() -> str:
    home = home_page_content(_settings())
    logo = _build_asset("static/media/logo-travelspace-white.webp") or _build_asset("static/media/logo-travelspace-white.png")
    brand = (f'<img src="{escape(logo, quote=True)}" alt="TRAVELSPACE" width="165" height="28">'
             if logo else "TRAVELSPACE")
    return (
        '<div data-seo-prerender="true" data-home-prerender="true">'
        '<header class="server-home-header">'
        f'<a href="/" aria-label="TRAVELSPACE — главная">{brand}</a>'
        '<a href="#server-navigation" aria-label="Меню"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg></a>'
        '</header><main><section class="home-hero">'
        '<div class="home-hero-backdrop" style="--mobile-home-image:url(/mobile-hero-sunset-v2.webp)" aria-hidden="true"></div>'
        '<div class="home-hero-shade" aria-hidden="true"></div><div class="home-hero-content">'
        f'<h1>{escape(home["h1"])}</h1>'
        + (f'<div class="home-hero-tagline">{_render_rich_paragraphs(home["hero_tagline"])}</div>' if home.get("hero_tagline") else "")
        + (f'<div class="home-hero-description">{_render_rich_paragraphs(home["hero_description"])}</div>' if home.get("hero_description") else "")
        + '<div class="home-hero-actions"><a href="/#avtobusnie-tury">Выбрать тур <span aria-hidden="true">→</span></a>'
        '<a href="/contacts">Получить консультацию</a></div></div></section>'
        '<div class="server-home-copy"><div id="server-navigation">'
        + _global_navigation() + '</div><div id="avtobusnie-tury">'
        + _render_homepage_sections() + '</div></div></main></div>'
    )


def _render_seo_hub_cover(seo: dict[str, Any]) -> str:
    src = str(seo.get("cover_image") or "").strip()
    if not src or not (
        (src.startswith("/") and not src.startswith("//"))
        or src.startswith(("https://", "http://"))
    ):
        return ""
    alt = _strip_html(seo.get("cover_alt") or seo.get("heading"))
    return (
        '<figure data-hub-cover="true">'
        f'<img src="{escape(src, quote=True)}" alt="{escape(alt, quote=True)}" '
        'width="1600" height="1000" loading="eager" decoding="async" '
        'style="width:100%;height:auto;aspect-ratio:8/5;object-fit:cover;object-position:center">'
        '</figure>'
    )


def _youtube_video_id(value: Any) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    iframe_src = re.search(
        r'<iframe\b[^>]*\bsrc=["\']([^"\']+)["\']',
        source,
        flags=re.IGNORECASE,
    )
    if iframe_src:
        source = iframe_src.group(1)
    source = source.replace("&amp;", "&")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", source):
        return source
    parsed = urlparse(source)
    hostname = str(parsed.hostname or "").lower()
    candidate = ""
    if hostname == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif hostname in {"youtube.com", "youtube-nocookie.com"} or hostname.endswith((".youtube.com", ".youtube-nocookie.com")):
        query_id = re.search(r"(?:^|&)v=([^&]*)", parsed.query)
        path_id = re.match(r"^/(?:embed|shorts|live)/([^/?#]+)", parsed.path)
        candidate = query_id.group(1) if query_id else path_id.group(1) if path_id else ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else ""



def _render_seo_hub_video(seo: dict[str, Any]) -> str:
    video_id = _youtube_video_id(seo.get("youtube_url"))
    if not video_id:
        return ""
    heading = _strip_html(seo.get("heading")) or "TRAVELSPACE"
    title = _strip_html(seo.get("youtube_title")) or f"Видео: {heading}"
    href = f"https://www.youtube.com/watch?v={video_id}"
    return (
        f'<section data-hub-youtube="true"><h2>{escape(title)}</h2><p>'
        f'<a href="{escape(href, quote=True)}" rel="noopener noreferrer">'
        'Посмотреть видео на YouTube</a></p></section>'
    )


def _home_render_assets(html: str) -> str:
    """Keep the first screen renderable without embedding the entire CSS file."""
    def defer_stylesheet(match):
        tag = match.group(0)
        href = re.search(r'href=["\'](/static/css/[^"\']+\.css)["\']', tag)
        if not href or not re.search(r'rel=["\']stylesheet["\']', tag):
            return tag
        asset_path = FRONTEND_BUILD_DIR / href.group(1).lstrip("/")
        if not asset_path.is_file():
            return tag
        url = escape(href.group(1), quote=True)
        return (
            f'<link rel="preload" as="style" href="{url}" '
            'onload="this.onload=null;this.rel=\'stylesheet\'">'
            f'<noscript><link rel="stylesheet" href="{url}"></noscript>'
        )

    html = re.sub(r'<link\b[^>]*>', defer_stylesheet, html, flags=re.IGNORECASE)
    try:
        assets = json.loads((FRONTEND_BUILD_DIR / "asset-manifest.json").read_text(encoding="utf-8")).get("files", {})
    except (OSError, ValueError):
        assets = {}
    preload = ''.join(
        f'<link rel="preload" as="script" href="{escape(url, quote=True)}">'
        for name, url in assets.items()
        if (name == "home.js" or re.fullmatch(r'static/js/home\.[a-z0-9]+\.chunk\.js', str(name)))
        and re.fullmatch(r'/static/js/home\.[a-z0-9]+\.chunk\.js', str(url))
    )
    critical_css = (
        '<style id="home-critical-style">'
        'html,body{margin:0;font-family:Manrope,Arial,sans-serif}'
        '.home-hero{position:relative;min-height:100vh;display:flex;align-items:center;overflow:hidden;background:#0a0906;color:#fff;line-height:1.5}'
        '.home-hero-backdrop{position:absolute;inset:0;background-color:#0a0a0a}'
        '.home-hero-shade{position:absolute;inset:0;background:linear-gradient(to bottom,rgb(0 0 0/.35),rgb(0 0 0/.30),rgb(0 0 0/.70)),rgb(67 20 7/.05)}'
        '@media(max-width:767px){.home-hero-backdrop{background-image:var(--mobile-home-image);background-size:cover;background-position:center;background-repeat:no-repeat}}'
        '.home-hero-content{position:relative;width:100%;max-width:1280px;margin:0 auto;padding:112px 16px 0;box-sizing:border-box}'
        '.home-hero h1{margin:12px 0 0;max-width:896px;font-size:36px;line-height:1.05;font-weight:700;letter-spacing:-.01em}'
        '.home-hero-tagline{margin-top:16px;max-width:768px;font-size:24px;line-height:1.25;font-weight:600;letter-spacing:-.01em}'
        '.home-hero-description{margin-top:20px;max-width:576px;font-size:16px;line-height:1.625;color:rgb(255 255 255/.85)}'
        '.home-hero p{margin:0}.home-hero p+p{margin-top:8px}'
        '.home-hero-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:32px}'
        '.home-hero-actions>a{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:0 24px;border-radius:9999px;background:#c2410c;color:#fff;font-size:16px;font-weight:500;text-decoration:none}'
        '.home-hero-actions>a+a{border:1px solid rgb(255 255 255/.4);background:rgb(255 255 255/.1)}'
        '@media(max-width:1023px){.home-hero{min-height:100svh}.home-hero-content{padding-top:96px;padding-bottom:calc(88px + env(safe-area-inset-bottom,0px))}}'
        '@media(max-width:639px) and (max-height:700px){.home-hero h1{font-size:30px}.home-hero-tagline{margin-top:12px;font-size:20px}.home-hero-description{margin-top:16px;font-size:14px;line-height:1.55}.home-hero-actions{margin-top:24px;gap:10px}}'
        '.server-home-header{position:absolute;top:0;left:0;right:0;z-index:1;display:flex;align-items:center;justify-content:space-between;height:64px;padding:0 16px;box-sizing:border-box;background:rgb(0 0 0/.25)}'
        '.server-home-header img{width:165px;height:28px;object-fit:contain}.server-home-header>a:last-child{display:grid;place-items:center;width:40px;height:40px;border-radius:50%;border:1px solid rgb(255 255 255/.2);color:#fff;background:rgb(255 255 255/.1)}'
        '@supports(content-visibility:auto){.server-home-copy{content-visibility:auto;contain-intrinsic-size:auto 5000px}}'
        '@media(min-width:640px){.home-hero-content{padding-left:24px;padding-right:24px}.home-hero h1{margin-top:16px;font-size:60px}.home-hero-tagline{font-size:30px}.home-hero-description{font-size:18px}}'
        '@media(min-width:1024px){.home-hero-content{padding:128px 32px 0}.home-hero h1{font-size:72px}.server-home-header{height:100px}}'
        '</style>'
    )
    mobile_photo_preload = '<link rel="preload" href="/mobile-hero-sunset-v2.webp" as="image" type="image/webp" media="(max-width: 767px)" fetchpriority="high">'
    return html.replace('</head>', critical_css + mobile_photo_preload + preload + '</head>')


def _render_snapshot(path: str, seo: dict[str, Any]) -> str:
    # The admin interface is client-rendered and has no public SEO content.
    if path == "/admin" or path.startswith("/admin/"):
        return ""
    if path == "/":
        return _home_first_screen()
    heading = escape(_strip_html(seo.get("heading") or seo.get("title") or DEFAULT_TITLE))
    is_landing = path in _landing_pages()
    parts = [
        '<div data-seo-prerender="true" style="max-width:1180px;margin:0 auto;padding:24px;font-family:Arial,sans-serif">',
        _global_navigation(),
        f"<main><h1>{heading}</h1>",
    ]
    if not is_landing:
        parts.append(
            _render_rich_paragraphs(
                seo.get("intro") or seo.get("description"), limit=1
            )
        )
    if path == "/":
        home = home_page_content(_settings())
        parts.append(_render_rich_paragraphs(home["hero_tagline"]))
        parts.append(_render_rich_paragraphs(home["hero_description"]))
        parts.append(_render_homepage_sections())
    elif path == "/tours":
        parts.append("<h2>Актуальные туры</h2>")
        parts.append(_tour_list(tour for tour in list_items("tours") if is_listed_tour(tour)))
    elif is_landing:
        cover = _render_seo_hub_cover(seo)
        if cover:
            parts.append(cover)
        intro = _render_rich_paragraphs(seo.get("intro"))
        if intro:
            parts.append(intro)
        catalog_title = (
            _strip_html(seo.get("catalog_title")) or "Выберите подходящий тур"
        )
        parts.append(f"<h2>{escape(catalog_title)}</h2>")
        parts.append(_tour_list(tours_for_landing(path)))
        video = _render_seo_hub_video(seo)
        if video:
            parts.append(video)
        content = _render_seo_hub_content(seo)
        if content:
            parts.append(content)
        how_to_title = _strip_html(seo.get("how_to_title")) or "Как выбрать тур"
        parts.append(f"<h2>{escape(how_to_title)}</h2><p>Сравните даты, длительность, программу и включённые услуги. Менеджер TRAVELSPACE поможет подобрать подходящую поездку и ответит на вопросы.</p>")
        faq = _render_seo_hub_faq(seo)
        if faq:
            parts.append(faq)
    elif path == "/blog":
        parts.append("<ul>")
        for article in list_items("articles"):
            if is_listed_article(article):
                preview = _limit(article.get("excerpt") or article.get("content"), 260)
                parts.append(f"<li>{_link('/blog/' + article['slug'], article.get('title'))}<p>{escape(preview)}</p></li>")
        parts.append("</ul>")
    elif path in STATIC_PAGE_FALLBACKS:
        parts.append(_render_static_page_content(path))
    elif path.startswith("/tours/") and seo.get("record"):
        tour = seo["record"]
        description = _render_paragraphs(
            tour.get("description") or tour.get("short_description"), limit=None
        )
        if description:
            parts.append(
                _tour_anchor_markers(tour, "about", "about-tour")
                + f"<h2>О туре</h2>{description}"
            )
        gallery = _render_tour_gallery(tour)
        if gallery:
            parts.append(
                _tour_anchor_markers(tour, "gallery", "gallery")
                + f"<h2>Фотографии тура</h2>{gallery}"
            )
        for label, key in (
            ("Главные впечатления тура", "highlights"),
            ("Что посмотреть", "what_to_see"),
        ):
            content = _render_list(tour.get(key))
            if content:
                parts.append(
                    _tour_anchor_markers(
                        tour,
                        key,
                        "highlights" if key == "highlights" else "",
                    )
                    + f"<h2>{label}</h2>{content}"
                )
        program = _render_tour_program(tour.get("program"))
        if program:
            parts.append(
                _tour_anchor_markers(tour, "program", "program")
                + f"<h2>Программа тура</h2>{program}"
            )
        price_marker_rendered = False
        for label, key in (
            ("В стоимость включено", "included"),
            ("В стоимость не включено", "excluded"),
        ):
            content = _render_list(tour.get(key))
            if content:
                marker = ""
                if not price_marker_rendered:
                    marker = _tour_anchor_markers(tour, "price", "price")
                    price_marker_rendered = True
                parts.append(marker + f"<h2>{label}</h2>{content}")
        youtube_id = _youtube_video_id(tour.get("youtube_url"))
        videos = _render_tour_videos(tour)
        if videos:
            parts.append(
                ("" if youtube_id else _tour_anchor_markers(tour, "videos"))
                + f"<h2>Видео о туре</h2>{videos}"
            )
        dates_and_prices = _render_tour_dates_and_prices(tour)
        if dates_and_prices:
            parts.append(
                _tour_anchor_markers(tour, "dates", "dates-prices")
                + f"<h2>Даты и стоимость</h2>{dates_and_prices}"
            )
        has_hotels = any(
            isinstance(chain, dict) and isinstance(chain.get("hotels"), list) and chain["hotels"]
            for chain in (tour.get("chains") if isinstance(tour.get("chains"), list) else [])
        )
        if has_hotels:
            parts.append(_tour_anchor_markers(tour, "hotels"))
        published_hotels = hotel_records([tour], public=True)
        if published_hotels:
            hotel_links = "".join(
                f'<li><a href="/hotels/{escape(hotel["slug"], quote=True)}">'
                f'{escape(hotel["name"])}</a></li>'
                for hotel in published_hotels
            )
            parts.append(f"<h2>Отели в туре</h2><ul>{hotel_links}</ul>")
        if youtube_id:
            youtube_title = _strip_html(tour.get("youtube_title")) or "Видео о туре"
            parts.append(
                _tour_anchor_markers(tour, "videos")
                + '<section data-tour-youtube="true">'
                + f"<h2>{escape(youtube_title)}</h2>"
                + f'<p><a href="https://www.youtube.com/watch?v={youtube_id}">'
                + "Посмотреть видео на YouTube</a></p></section>"
            )
        important = _render_list(tour.get("important_info"))
        if important:
            parts.append(
                _tour_anchor_markers(tour, "important")
                + f"<h2>Важная информация</h2>{important}"
            )
        related = _render_related_tours(tour)
        if related:
            related_title = (
                _strip_html(tour.get("related_tours_title"))
                or "Туры, которые вас также могут заинтересовать"
            )
            parts.append(
                _tour_anchor_markers(tour, "related")
                + f"<h2>{escape(related_title)}</h2>{related}"
            )
        faq = _render_tour_faq(tour.get("faq"))
        if faq:
            parts.append(
                _tour_anchor_markers(tour, "faq", "faq")
                + f"<h2>Часто задаваемые вопросы</h2>{faq}"
            )
    elif path.startswith("/hotels/") and seo.get("record"):
        hotel = seo["record"]
        parts.append(_render_rich_paragraphs(hotel.get("description")))
        for field, label in (("meal_description", "Питание"), ("location_description", "Расположение"), ("beach", "Пляж"), ("transfer", "Трансфер"), ("rules", "Условия проживания")):
            if hotel.get(field):
                parts.append(f'<h2>{label}</h2>{_render_rich_paragraphs(hotel[field])}')
        for field, label in (("amenities", "Удобства"), ("nearby", "Рядом с отелем")):
            if hotel.get(field):
                parts.append(f'<h2>{label}</h2>{_render_list(hotel[field])}')
        if hotel.get("rooms"):
            parts.append('<h2>Номера</h2>')
            for room in hotel["rooms"]:
                parts.append(f'<h3>{escape(str(room.get("title") or room.get("number") or "Номер"))}</h3>{_render_rich_paragraphs(room.get("description"))}')
        parts.append(f'<p>{_link("/tours/" + hotel["tour_slug"] + "#" + hotel["tour_hotel_anchor"], "Даты и цены в туре")}</p>')
    elif path.startswith("/blog/") and seo.get("record"):
        parts.append(_render_article_body(seo["record"]))
        parts.append(f"<p>{_link('/tours', 'Посмотреть актуальные туры')}</p>")
    if seo.get("page_faq_items"):
        parts.append(f'<section><h2>{escape(str(seo["page_faq_title"]))}</h2>')
        for item in seo["page_faq_items"]:
            parts.append(f'<h3>{_render_rich_inline(item["question"])}</h3>{_render_rich_paragraphs(item["answer"])}')
        parts.append("</section>")
    parts.append("</main></div>")
    return "".join(parts)


PUBLIC_RECORD_FIELDS = set("""
id slug title title_highlighted transport_type active hidden hide_from_catalog order
tagline short_description description region_name region_slug direction_name duration
departure_city departure_cities departureCities price price_from currency additional_price
additional_currency price_type badges hero_image hero_image_alt hero_mobile hero_mobile_image
mobile_hero_image og_image gallery gallery_alts images cover cover_alt image
dates chains hotels use_hotel_chains program highlights what_to_see included excluded
important_info section_anchors faq map_embed content excerpt related_tour_slugs related_tours_title videos youtube_title youtube_url seo_title seo_description
seo_h1 seo_image seo_canonical_url seo_noindex seo_nofollow seo_lastmod published_at updated_at
content_blocks gallery_alts image_alts name text rating date photo question answer show_on_home category valid_until related_tour_slug
button_text button_url discount value subtitle tour_name
hotel_id tour_id tour_slug tour_title chain_id chain_title tour_hotel_anchor rooms
meal meal_description location address location_description nearby amenities beach
transfer check_in check_out rules stars map_url page_enabled
""".split())
PUBLIC_SETTINGS_FIELDS = set("""
company_short company_name address email phone phone_link site_url work_hours header_phones
contact_phones social_buttons call_directions map_embed_url map_iframe_url map_route_url map_url
home_page home_benefits seo_pages seo_hubs seo_default_image links_page
gtm_id google_analytics_id yandex_metrika_id facebook_pixel_id meta_pixel_id tiktok_pixel_id
""".split())
CARD_FIELDS = set("""
id slug title title_highlighted transport_type active hidden hide_from_catalog order tagline
short_description region_name region_slug direction_name duration departure_city departure_cities departureCities
price price_from currency additional_price additional_currency price_type badges hero_image
hero_image_alt hero_mobile hero_mobile_image mobile_hero_image dates chains
""".split())

HOME_REVIEW_FIELDS = {
    "id", "name", "text", "rating", "date", "photo", "tour_name", "direction",
}
HOME_PROMOTION_FIELDS = {
    "id", "title", "description", "image", "related_tour_slug", "related_tour_slugs",
}


def _public_record(record: dict | None, fields: set[str] = PUBLIC_RECORD_FIELDS) -> dict | None:
    if not isinstance(record, dict):
        return None
    return {key: value for key, value in record.items() if key in fields}


def _script_json(value: Any) -> str:
    # A literal </script> inside admin-authored content must not end this element.
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _gtm_container_id(settings: Any) -> str:
    """Return a safe public GTM container ID from the editable settings."""
    if not isinstance(settings, dict):
        return ""
    analytics = settings.get("analytics")
    nested = analytics.get("gtm_id") if isinstance(analytics, dict) else ""
    value = str(settings.get("gtm_id") or nested or "").strip().upper()
    return value if re.fullmatch(r"GTM-[A-Z0-9]+", value) else ""


def _gtm_head_script(container_id: str) -> str:
    identifier = json.dumps(container_id)
    return (
        '<script data-server-gtm="true">'
        '(function(w,d,i){w.dataLayer=w.dataLayer||[];'
        'w.__TRAVELSPACE_GTM_CONFIGURED=true;'
        'w.__TRAVELSPACE_GTM_ID=i;'
        'function load(){'
        'if(w.__TRAVELSPACE_GTM_INITIALIZED)return;'
        'w.__TRAVELSPACE_GTM_INITIALIZED=true;'
        "w.dataLayer.push({'gtm.start':new Date().getTime(),event:'gtm.js'});"
        "var f=d.getElementsByTagName('script')[0],j=d.createElement('script');"
        "j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+encodeURIComponent(i);"
        'f.parentNode.insertBefore(j,f);'
        "w.dispatchEvent(new Event('gtm-ready'));}"
        'w.__TRAVELSPACE_LOAD_GTM=load;'
        "['pointerdown','keydown','touchstart','wheel'].forEach(function(name){"
        "w.addEventListener(name,load,{once:true,passive:true});});"
        "w.addEventListener('load',function(){w.setTimeout(load,1500);},{once:true});"
        '})(window,document,' + identifier + ');'
        '</script>'
    )


def _gtm_noscript(container_id: str) -> str:
    return (
        '<noscript data-server-gtm="true"><iframe '
        f'src="https://www.googletagmanager.com/ns.html?id={escape(container_id, quote=True)}" '
        'height="0" width="0" style="display:none;visibility:hidden" '
        'title="Google Tag Manager"></iframe></noscript>'
    )


def _page_bootstrap(path: str, seo: dict[str, Any]) -> dict:
    settings = _settings()
    tours = []
    for tour in list_items("tours"):
        if not is_listed_tour(tour):
            continue
        card = _public_record(tour, CARD_FIELDS)
        # Menus/cards need dates and prices, not every hotel's full description.
        if isinstance(card.get("chains"), list):
            card["chains"] = [_public_record(chain, {"id", "name", "active", "dates"})
                              for chain in card["chains"] if isinstance(chain, dict)]
        tours.append(card)
    articles = []
    for article in list_items("articles"):
        if not is_listed_article(article):
            continue
        if path == "/":
            # The home page only uses these records in the Blog menu. Avoid
            # parsing article bodies and shipping gallery data before paint.
            summary = _public_record(
                article,
                {
                    "id", "slug", "title", "published_at", "active",
                    "hidden", "hidden_from_list", "hide_from_list", "order",
                },
            )
        else:
            summary = _public_record(article, {"id", "slug", "title", "excerpt", "cover", "images", "seo_image", "seo_description", "gallery", "published_at", "active", "hidden", "order"})
            summary["excerpt"] = _limit(_first_text(article.get("excerpt"), article.get("content")), 190)
        articles.append(summary)
    status = get_http_status_for_path(path)
    # The home screen does not need the full editable SEO-hub payload. It is
    # several dozen kilobytes of article-like text and is still available from
    # the settings API for pages that need it.
    bootstrap_settings = {
        key: value
        for key, value in settings.items()
        if key in PUBLIC_SETTINGS_FIELDS
        and not (path == "/" and key == "seo_hubs")
    }
    if path == "/":
        # Keep custom direction labels available to the header without
        # embedding all of their long landing-page copy on the home screen.
        bootstrap_settings["seo_hubs"] = {
            str(slug): {
                key: value
                for key, value in hub.items()
                if key in {"custom", "label", "heading", "title", "path"}
            }
            for slug, hub in (settings.get("seo_hubs") or {}).items()
            if isinstance(hub, dict)
        }
        # Only the home SEO configuration is read while this document is
        # mounted. Other public pages receive their complete settings on their
        # own server-rendered navigation.
        home_seo = (settings.get("seo_pages") or {}).get("home")
        bootstrap_settings["seo_pages"] = {"home": home_seo} if isinstance(home_seo, dict) else {}

    if path == "/":
        # Match the actual home render: four review cards, three promotions,
        # and only FAQ entries enabled for the home block.
        reviews = [
            _public_record(item, HOME_REVIEW_FIELDS)
            for item in sort_reviews(
                item
                for item in list_items("reviews")
                if item.get("active") is not False
            )
        ][:4]
        promotions = [
            _public_record(item, HOME_PROMOTION_FIELDS)
            for item in list_items("promotions")
            if item.get("active") is not False
        ][:3]
        faq = [
            _public_record(item)
            for item in list_items("faq")
            if item.get("active") is not False and item.get("show_on_home") is not False
        ]
    else:
        reviews = [
            _public_record(item)
            for item in sort_reviews(
                item
                for item in list_items("reviews")
                if item.get("active") is not False
            )
        ]
        promotions = [
            _public_record(item)
            for item in list_items("promotions")
            if item.get("active") is not False
        ]
        faq = [
            _public_record(item)
            for item in list_items("faq")
            if item.get("active") is not False
        ]

    return {
        "version": 1, "path": path, "status": status,
        "record": _public_record(seo.get("record")) if status == 200 else None,
        "seo": {
            "title": _limit(_first_text(seo.get("title"), DEFAULT_TITLE), 80),
            "description": _limit(_first_text(seo.get("description"), DEFAULT_DESCRIPTION), 180),
            "canonical": seo.get("canonical_url") or _page_url(path),
            "image": _absolute_url(seo.get("image")),
            "noIndex": bool(seo.get("no_index")), "noFollow": bool(seo.get("no_follow")),
            "type": seo.get("type") or "website", "siteName": SITE_NAME,
            "graph": _structured_graph(path, seo),
        },
        "site": {"settings": bootstrap_settings,
                 "tours": tours, "articles": articles, "ready": True},
        "collections": {
            "reviews": reviews,
            "promotions": promotions,
            "faq": faq,
        },
    }


def render_index_html(path: str) -> str:
    if not INDEX_HTML_PATH.exists():
        return ""
    clean_path = _clean_path(path)
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    for pattern in SEO_TAG_PATTERNS:
        html = re.sub(pattern, "", html, flags=re.IGNORECASE | re.DOTALL)
    seo = get_seo_for_path(clean_path)
    html = re.sub(r"<head>", lambda _: "<head>" + _render_meta_block(clean_path, seo), html, count=1, flags=re.IGNORECASE)
    if not clean_path.startswith(("/admin", "/api")):
        gtm_id = _gtm_container_id(_settings())
        if gtm_id:
            html = re.sub(
                r"<head>",
                lambda _: "<head>" + _gtm_head_script(gtm_id),
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            html = re.sub(
                r"<body\b[^>]*>",
                lambda match: match.group(0) + _gtm_noscript(gtm_id),
                html,
                count=1,
                flags=re.IGNORECASE,
            )
    snapshot = _render_snapshot(clean_path, seo)
    html = re.sub(
        r'<div\s+id=["\']root["\']\s*>\s*</div>',
        lambda _: f'<div id="root">{snapshot}</div>',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if not clean_path.startswith(("/admin", "/api")):
        bootstrap = _script_json(_page_bootstrap(clean_path, seo))
        html = html.replace("</body>", f'<script id="page-bootstrap" type="application/json">{bootstrap}</script></body>')
        # The production template contains a non-empty branded cover, so it
        # stays over the snapshot. Keep the legacy empty-cover cleanup for
        # minimal test/old templates. The noscript helper text is unnecessary
        # because the server snapshot itself is the no-JS fallback.
        html = re.sub(r'<div\s+id="initial-load-cover"[^>]*>\s*</div>', "", html)
        html = re.sub(r'<noscript>\s*You need to enable JavaScript to run this app\.\s*</noscript>', "", html)
        fallback_css = ('<style id="server-page-style">[data-seo-prerender]{color:#171717;line-height:1.65;overflow-wrap:anywhere}'
                        '[data-seo-prerender] h1{font-size:clamp(26px,4vw,44px);font-weight:800;margin:24px 0 16px}'
                        '[data-seo-prerender] h2{font-size:24px;font-weight:700;margin:24px 0 12px}'
                        '[data-seo-prerender] h3{font-size:19px;font-weight:700;margin:16px 0 8px}'
                        '[data-seo-prerender] p{margin:10px 0}[data-seo-prerender] a{color:#C2410C;text-decoration:none}'
                        '[data-seo-prerender] img{max-width:100%;height:auto}[data-seo-prerender] ul{padding-left:24px;list-style:disc}'
                        '[data-seo-prerender] table{width:100%;border-collapse:collapse}[data-seo-prerender] td,'
                        '[data-seo-prerender] th{border:1px solid #ddd;padding:8px;text-align:left}</style>')
        if clean_path == "/":
            # Generic readable fallback styles belong to the lower copy. The
            # hero uses the same production rules before and after React mounts.
            fallback_css = fallback_css.replace('[data-seo-prerender]', '.server-home-copy')
            html = _home_render_assets(html)
        html = html.replace("</head>", fallback_css + "</head>")
    return html


def _sitemap_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    display_date = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if display_date:
        day, month, year = display_date.groups()
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) else None


def build_sitemap_xml() -> str:
    settings = _settings()
    home_lastmod = _sitemap_date(settings.get("home_content_updated_at"))
    seo_hubs = seo_hubs_with_defaults(settings)
    entries: list[tuple[str, str | None]] = [
        (path, home_lastmod if path == "/" else None)
        for path in STATIC_PAGE_FALLBACKS
    ]
    entries.extend(
        (
            path,
            _sitemap_date(
                seo_hubs.get(_seo_hub_slug(path), {}).get("content_updated_at")
            ),
        )
        for path in _landing_pages(settings)
    )
    for tour in list_items("tours"):
        if is_indexable_tour(tour):
            entries.append((f"/tours/{tour['slug']}", _sitemap_date(tour.get("seo_lastmod") or tour.get("content_updated_at") or tour.get("updated_at") or tour.get("created_at"))))
    for article in list_items("articles"):
        if is_indexable_article(article):
            entries.append((f"/blog/{article['slug']}", _sitemap_date(article.get("seo_lastmod") or article.get("content_updated_at") or article.get("updated_at") or article.get("published_at"))))
    for hotel in hotel_records(list_items("tours"), public=True):
        if not hotel.get("seo_noindex"):
            entries.append((f'/hotels/{hotel["slug"]}', _sitemap_date(hotel.get("updated_at"))))
    unique: dict[str, str | None] = {}
    for path, lastmod in entries:
        unique.setdefault(_clean_path(path), lastmod)
    xml_entries = []
    for path, lastmod in unique.items():
        lines = ["  <url>", f"    <loc>{escape(_page_url(path))}</loc>"]
        if lastmod:
            lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        lines.append("  </url>")
        xml_entries.append("\n".join(lines))
    body = "\n".join(xml_entries)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


def build_robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /api/admin\n"
        "Disallow: /api/auth\n"
        f"Sitemap: {PUBLIC_SITE_URL}/sitemap.xml\n"
    )
