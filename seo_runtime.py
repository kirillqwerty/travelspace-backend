"""Server-side SEO rendering for the React application.

Search engines receive unique metadata and a semantic HTML snapshot for every
public URL. React replaces the snapshot after it starts in the browser.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterable

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
DEFAULT_TITLE = "TRAVELSPACE — автобусные и авиационные туры из Минска"
DEFAULT_DESCRIPTION = (
    "Авторские автобусные и авиационные туры из Минска: Грузия, Дагестан, "
    "Санкт-Петербург, Карелия и другие направления."
)
DEFAULT_IMAGE = "/og-image.jpg"


STATIC_PAGE_FALLBACKS: dict[str, dict[str, str]] = {
    "/": {
        "title": "TRAVELSPACE — автобусные и авиационные туры из Минска",
        "description": "Туры из Минска в Грузию, Дагестан, Санкт-Петербург, Карелию, Турцию и другие направления.",
        "heading": "Авторские туры из Минска",
    },
    "/tours": {
        "title": "Каталог туров из Минска | TRAVELSPACE",
        "description": "Актуальные автобусные и авиационные туры из Минска: даты, цены, программа и бронирование.",
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


LANDING_PAGES: dict[str, dict[str, Any]] = {
    "/tours/avtobusnye-iz-minska": {
        "title": "Автобусные туры из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры из Минска в Грузию, Дагестан, Санкт-Петербург, Карелию, Абхазию и другие направления.",
        "heading": "Автобусные туры из Минска",
        "kind": "bus",
    },
    "/tours/avia-iz-minska": {
        "title": "Авиационные туры из Минска 2026 | TRAVELSPACE",
        "description": "Туры с перелётом из Минска: актуальные направления, программы, даты и стоимость поездок.",
        "heading": "Авиационные туры из Минска",
        "kind": "air",
    },
    "/tours/gruziya": {
        "title": "Туры в Грузию из Минска 2026 | TRAVELSPACE",
        "description": "Туры в Грузию из Минска: отдых на море, экскурсии, даты, программа и стоимость поездки.",
        "heading": "Туры в Грузию из Минска",
        "keywords": ("груз", "gruzi"),
    },
    "/tours/sankt-peterburg": {
        "title": "Автобусный тур в Санкт-Петербург из Минска | TRAVELSPACE",
        "description": "Туры в Санкт-Петербург и Питер из Минска на выходные: программа, даты, отели и стоимость.",
        "heading": "Туры в Санкт-Петербург из Минска",
        "keywords": ("петербург", "питер", "peterburg"),
    },
    "/tours/dagestan": {
        "title": "Туры в Дагестан из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Дагестан из Минска: горы, каньоны, экскурсии, даты и стоимость.",
        "heading": "Туры в Дагестан из Минска",
        "keywords": ("дагест", "dagestan"),
    },
    "/tours/kareliya": {
        "title": "Туры в Карелию из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Карелию из Минска: Рускеала, Кижи, Ладожские шхеры, даты и программа.",
        "heading": "Туры в Карелию из Минска",
        "keywords": ("карел", "kareli"),
    },
    "/tours/abhaziya": {
        "title": "Туры в Абхазию из Минска 2026 | TRAVELSPACE",
        "description": "Автобусные туры в Абхазию из Минска: море, экскурсии, программа, даты и стоимость.",
        "heading": "Туры в Абхазию из Минска",
        "keywords": ("абхаз", "abhaz"),
    },
    "/tours/severnaya-osetiya": {
        "title": "Туры в Северную Осетию из Минска | TRAVELSPACE",
        "description": "Автобусные туры в Северную Осетию из Минска: горные маршруты, программа, даты и цены.",
        "heading": "Туры в Северную Осетию из Минска",
        "keywords": ("осети", "oseti"),
    },
    "/tours/moskva": {
        "title": "Автобусные туры в Москву из Минска | TRAVELSPACE",
        "description": "Туры в Москву из Минска на выходные: экскурсионная программа, даты, отель и стоимость.",
        "heading": "Туры в Москву из Минска",
        "keywords": ("москв", "moskv"),
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


def _limit(value: Any, max_len: int) -> str:
    text = _strip_html(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip(" ,.;:-") + "…"


def _absolute_url(value: str | None) -> str:
    value = str(value or DEFAULT_IMAGE).strip()
    if value.startswith(("http://", "https://")):
        return value
    return PUBLIC_SITE_URL + "/" + value.lstrip("/")


def _page_url(path: str) -> str:
    return PUBLIC_SITE_URL + _clean_path(path)


def _settings() -> dict[str, Any]:
    data = load("settings", default={})
    return data if isinstance(data, dict) else {}


def is_public_tour(tour: Any) -> bool:
    return bool(
        isinstance(tour, dict)
        and tour.get("active", True)
        and not tour.get("hidden", False)
        and not tour.get("hide_from_catalog", False)
        and tour.get("slug")
    )


def is_public_article(article: Any) -> bool:
    return bool(isinstance(article, dict) and article.get("active", True) and article.get("slug"))


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
    config = LANDING_PAGES.get(_clean_path(path), {})
    tours = [tour for tour in list_items("tours") if is_public_tour(tour)]
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
    return {
        "title": selected.get("title") or fallback["title"],
        "description": selected.get("description") or fallback["description"],
        "heading": fallback["heading"],
        "image": selected.get("image") or settings.get("seo_default_image") or DEFAULT_IMAGE,
        "no_index": bool(selected.get("no_index", False)),
        "type": "website",
    }


def _landing_seo(path: str) -> dict[str, Any]:
    config = LANDING_PAGES[path]
    return {
        **config,
        "image": DEFAULT_IMAGE,
        "no_index": False,
        "type": "website",
    }


def _not_found(kind: str = "Страница") -> dict[str, Any]:
    return {
        "title": f"{kind} не найдена | TRAVELSPACE",
        "description": f"{kind} не найдена. Перейдите в каталог актуальных туров TRAVELSPACE.",
        "heading": f"{kind} не найдена",
        "image": DEFAULT_IMAGE,
        "no_index": True,
        "type": "website",
    }


def _tour_seo(slug: str, path: str) -> dict[str, Any]:
    tour = get_by("tours", "slug", slug)
    if not is_public_tour(tour):
        return _not_found("Тур")
    description = (
        tour.get("seo_description")
        or tour.get("short_description")
        or tour.get("tagline")
        or tour.get("description")
        or f"{tour.get('title', 'Тур')}: программа, даты и стоимость поездки."
    )
    structured = {
        "@type": "TouristTrip",
        "name": tour.get("title"),
        "description": _limit(description, 220),
        "url": _page_url(path),
        "image": _absolute_url(_tour_image(tour)),
        "touristType": "Групповой тур",
        "provider": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
    }
    return {
        "title": tour.get("seo_title") or f"{tour.get('title', 'Тур')} | TRAVELSPACE",
        "description": description,
        "heading": tour.get("title"),
        "image": _tour_image(tour),
        "no_index": False,
        "type": "article",
        "structured_data": structured,
        "record": tour,
    }


def _article_seo(slug: str, path: str) -> dict[str, Any]:
    article = get_by("articles", "slug", slug)
    if not is_public_article(article):
        return _not_found("Статья")
    description = article.get("seo_description") or article.get("excerpt") or article.get("content")
    structured: dict[str, Any] = {
        "@type": "Article",
        "headline": article.get("title"),
        "description": _limit(description, 220),
        "mainEntityOfPage": _page_url(path),
        "image": _absolute_url(article.get("seo_image") or article.get("cover") or DEFAULT_IMAGE),
        "author": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
        "publisher": {"@id": f"{PUBLIC_SITE_URL}/#organization"},
    }
    if article.get("published_at"):
        structured["datePublished"] = article["published_at"]
    if article.get("updated_at"):
        structured["dateModified"] = article["updated_at"]
    return {
        "title": article.get("seo_title") or f"{article.get('title', 'Статья')} | TRAVELSPACE",
        "description": description,
        "heading": article.get("title"),
        "image": article.get("seo_image") or article.get("cover") or DEFAULT_IMAGE,
        "no_index": False,
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
    if path in STATIC_PAGE_FALLBACKS or path in LANDING_PAGES or path in SERVICE_PAGES:
        return 200
    if path.startswith("/tours/"):
        slug = path.removeprefix("/tours/")
        return 200 if "/" not in slug and is_public_tour(get_by("tours", "slug", slug)) else 404
    if path.startswith("/blog/"):
        slug = path.removeprefix("/blog/")
        return 200 if "/" not in slug and is_public_article(get_by("articles", "slug", slug)) else 404
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
    if path in LANDING_PAGES:
        return _landing_seo(path)
    if path.startswith("/tours/"):
        return _tour_seo(path.removeprefix("/tours/").split("/", 1)[0], path)
    if path.startswith("/blog/"):
        return _article_seo(path.removeprefix("/blog/").split("/", 1)[0], path)
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
        items.append({
            "@type": "ListItem",
            "position": len(items) + 1,
            "name": _strip_html(seo.get("heading") or seo.get("title")),
            "item": _page_url(path),
        })
    return items


def _structured_graph(path: str, seo: dict[str, Any]) -> dict[str, Any]:
    settings = _settings()
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
            "@id": _page_url(path) + "#webpage",
            "url": _page_url(path),
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
        graph.append({key: value for key, value in seo["structured_data"].items() if key != "@context"})
    return _safe_json({"@context": "https://schema.org", "@graph": graph})


def _render_meta_block(path: str, seo: dict[str, Any]) -> str:
    title = _limit(seo.get("title") or DEFAULT_TITLE, 80)
    description = _limit(seo.get("description") or DEFAULT_DESCRIPTION, 180)
    image = _absolute_url(seo.get("image"))
    url = _page_url(path)
    robots = "noindex, follow" if seo.get("no_index") else "index, follow"
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
        f'<script{attr} type="application/ld+json">{json.dumps(_structured_graph(path, seo), ensure_ascii=False, separators=(",", ":"))}</script>',
    ]
    return "\n    " + "\n    ".join(lines) + "\n"


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        clean = _strip_html(value)
        return [clean] if clean else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_text(item))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if key not in {"id", "image", "icon", "map_embed", "slug"}:
                result.extend(_flatten_text(item))
        return result
    return []


def _render_paragraphs(value: Any, limit: int = 8, semantic_headings: bool = False) -> str:
    chunks: list[str] = []
    if isinstance(value, str):
        chunks = [part.strip() for part in re.split(r"\n\s*\n|\r?\n", value) if part.strip()]
    else:
        chunks = _flatten_text(value)
    rendered: list[str] = []
    for chunk in chunks[:limit]:
        clean = _limit(chunk, 900)
        semantic = re.match(r"^(\d+)\.\s+(.+?[.!?])(?:\s+(.+))?$", clean) if semantic_headings else None
        if semantic:
            rendered.append(f"<h2>{escape(semantic.group(1) + '. ' + semantic.group(2))}</h2>")
            if semantic.group(3):
                rendered.append(f"<p>{escape(semantic.group(3))}</p>")
        else:
            rendered.append(f"<p>{escape(clean)}</p>")
    return "".join(rendered)


def _link(path: str, label: Any) -> str:
    return f'<a href="{escape(_page_url(path), quote=True)}">{escape(_strip_html(label))}</a>'


def _tour_list(tours: Iterable[dict[str, Any]]) -> str:
    items = []
    for tour in tours:
        description = tour.get("short_description") or tour.get("tagline") or tour.get("description")
        items.append(
            "<li>"
            + _link(f"/tours/{tour['slug']}", tour.get("title") or "Тур")
            + (f"<p>{escape(_limit(description, 240))}</p>" if description else "")
            + "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>Новые даты и маршруты скоро появятся в каталоге.</p>"


def _global_navigation() -> str:
    links = [
        ("/tours", "Все туры"),
        ("/tours/avtobusnye-iz-minska", "Автобусные туры"),
        ("/tours/avia-iz-minska", "Авиационные туры"),
        ("/tours/gruziya", "Грузия"),
        ("/tours/sankt-peterburg", "Санкт-Петербург"),
        ("/tours/dagestan", "Дагестан"),
        ("/tours/kareliya", "Карелия"),
        ("/blog", "Блог"),
        ("/contacts", "Контакты"),
    ]
    return '<nav aria-label="Основная навигация">' + " ".join(_link(path, label) for path, label in links) + "</nav>"


def _render_snapshot(path: str, seo: dict[str, Any]) -> str:
    heading = escape(_strip_html(seo.get("heading") or seo.get("title") or DEFAULT_TITLE))
    parts = [
        '<div data-seo-prerender="true" style="max-width:1180px;margin:0 auto;padding:24px;font-family:Arial,sans-serif">',
        _global_navigation(),
        f"<main><h1>{heading}</h1>",
        f"<p>{escape(_limit(seo.get('description'), 360))}</p>",
    ]
    if path == "/" or path == "/tours":
        parts.append("<h2>Актуальные туры</h2>")
        parts.append(_tour_list(tour for tour in list_items("tours") if is_public_tour(tour)))
        if path == "/":
            articles = [article for article in list_items("articles") if is_public_article(article)]
            if articles:
                parts.append("<h2>Полезное о путешествиях</h2><ul>")
                parts.extend(f"<li>{_link('/blog/' + article['slug'], article.get('title'))}</li>" for article in articles)
                parts.append("</ul>")
    elif path in LANDING_PAGES:
        parts.append("<h2>Подходящие программы</h2>")
        parts.append(_tour_list(tours_for_landing(path)))
        parts.append("<h2>Как выбрать тур</h2><p>Сравните даты, длительность, программу и включённые услуги. Менеджер TRAVELSPACE поможет подобрать подходящую поездку и ответит на вопросы.</p>")
    elif path == "/blog":
        parts.append("<ul>")
        for article in list_items("articles"):
            if is_public_article(article):
                parts.append(f"<li>{_link('/blog/' + article['slug'], article.get('title'))}<p>{escape(_limit(article.get('excerpt') or article.get('content'), 260))}</p></li>")
        parts.append("</ul>")
    elif path.startswith("/tours/") and seo.get("record"):
        tour = seo["record"]
        for label, key in (
            ("О туре", "description"),
            ("Что вас ждёт", "highlights"),
            ("Что увидим", "what_to_see"),
            ("Программа тура", "program"),
            ("В стоимость включено", "included"),
            ("Важная информация", "important_info"),
        ):
            content = _render_paragraphs(tour.get(key))
            if content:
                parts.append(f"<h2>{label}</h2>{content}")
    elif path.startswith("/blog/") and seo.get("record"):
        parts.append(_render_paragraphs(seo["record"].get("content"), limit=40, semantic_headings=True))
        parts.append(f"<p>{_link('/tours', 'Посмотреть актуальные туры')}</p>")
    parts.append("</main></div>")
    return "".join(parts)


def render_index_html(path: str) -> str:
    if not INDEX_HTML_PATH.exists():
        return ""
    clean_path = _clean_path(path)
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    for pattern in SEO_TAG_PATTERNS:
        html = re.sub(pattern, "", html, flags=re.IGNORECASE | re.DOTALL)
    seo = get_seo_for_path(clean_path)
    html = re.sub(r"<head>", "<head>" + _render_meta_block(clean_path, seo), html, count=1, flags=re.IGNORECASE)
    snapshot = _render_snapshot(clean_path, seo)
    html = re.sub(
        r'<div\s+id=["\']root["\']\s*>\s*</div>',
        f'<div id="root">{snapshot}</div>',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    return html


def _sitemap_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) else None


def build_sitemap_xml() -> str:
    entries: list[tuple[str, str | None]] = [(path, None) for path in STATIC_PAGE_FALLBACKS]
    entries.extend((path, None) for path in LANDING_PAGES)
    for tour in list_items("tours"):
        if is_public_tour(tour):
            entries.append((f"/tours/{tour['slug']}", _sitemap_date(tour.get("updated_at") or tour.get("created_at"))))
    for article in list_items("articles"):
        if is_public_article(article):
            entries.append((f"/blog/{article['slug']}", _sitemap_date(article.get("updated_at") or article.get("published_at"))))
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
