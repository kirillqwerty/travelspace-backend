"""Runtime SEO helpers for serving a React SPA through FastAPI.

This module reads frontend/build/index.html and returns the same React app
with per-URL title, description, canonical, Open Graph, Twitter and JSON-LD.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from storage import get_by, list_items, load

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
FRONTEND_BUILD_DIR = Path(
    os.environ.get("FRONTEND_BUILD_DIR") or PROJECT_DIR / "frontend" / "build"
)
INDEX_HTML_PATH = FRONTEND_BUILD_DIR / "index.html"
PUBLIC_SITE_URL = os.environ.get("PUBLIC_SITE_URL", "https://travelspace.by").rstrip("/")
SITE_NAME = "TRAVELSPACE"
DEFAULT_TITLE = "TRAVELSPACE — автобусные туры из Минска"
DEFAULT_DESCRIPTION = (
    "Автобусные туры из Минска в Грузию, Дагестан, Санкт-Петербург и Карелию. "
    "Продуманные программы, заботливые гиды и понятная цена."
)
DEFAULT_IMAGE = "/og-image.jpg"

STATIC_PAGE_FALLBACKS: dict[str, dict[str, str]] = {
    "/": {
        "title": "TRAVELSPACE — автобусные туры из Минска",
        "description": "Автобусные туры из Минска в Грузию, Дагестан, Санкт-Петербург и Карелию.",
        "image": DEFAULT_IMAGE,
    },
    "/tours": {
        "title": "Каталог автобусных туров из Минска | TRAVELSPACE",
        "description": "Актуальные автобусные туры из Минска: даты, цены, программа, отели и заявки онлайн.",
        "image": DEFAULT_IMAGE,
    },
    "/about": {
        "title": "О компании TRAVELSPACE — туроператор из Минска",
        "description": "TRAVELSPACE разрабатывает автобусные туры из Минска и сопровождает группы в поездках.",
        "image": DEFAULT_IMAGE,
    },
    "/contacts": {
        "title": "Контакты TRAVELSPACE",
        "description": "Телефоны, email, офис, режим работы и форма заявки на подбор тура.",
        "image": DEFAULT_IMAGE,
    },
    "/faq": {
        "title": "Частые вопросы о турах | TRAVELSPACE",
        "description": "Ответы на вопросы о бронировании, оплате, документах и автобусных турах TRAVELSPACE.",
        "image": DEFAULT_IMAGE,
    },
    "/promotions": {
        "title": "Акции и спецпредложения на туры | TRAVELSPACE",
        "description": "Актуальные акции, скидки и спецпредложения на автобусные туры из Минска.",
        "image": DEFAULT_IMAGE,
    },
    "/reviews": {
        "title": "Отзывы туристов | TRAVELSPACE",
        "description": "Отзывы туристов о поездках, маршрутах и работе TRAVELSPACE.",
        "image": DEFAULT_IMAGE,
    },
    "/blog": {
        "title": "Блог о путешествиях | TRAVELSPACE",
        "description": "Полезные статьи, чек-листы и советы для комфортных автобусных туров.",
        "image": DEFAULT_IMAGE,
    },
    "/agencies": {
        "title": "Агентствам — сотрудничество с TRAVELSPACE",
        "description": "Условия сотрудничества для турагентств: блоки мест, материалы и поддержка менеджера.",
        "image": DEFAULT_IMAGE,
    },
    "/payment": {
        "title": "Оплата тура через ЕРИП | TRAVELSPACE",
        "description": "Как оплатить тур TRAVELSPACE через ЕРИП после бронирования и заключения договора.",
        "image": DEFAULT_IMAGE,
    },
    "/legal": {
        "title": "Юридическая информация | TRAVELSPACE",
        "description": "Политика конфиденциальности, согласие на обработку персональных данных и реквизиты.",
        "image": DEFAULT_IMAGE,
    },
}

SEO_TAG_PATTERNS = [
    r"<title>.*?</title>",
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
    text = re.sub(r"[*_`#>\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _limit(value: Any, max_len: int) -> str:
    text = _strip_html(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _absolute_url(value: str | None) -> str:
    if not value:
        value = DEFAULT_IMAGE
    value = str(value).strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if not value.startswith("/"):
        value = "/" + value
    return PUBLIC_SITE_URL + value


def _page_url(path: str) -> str:
    return PUBLIC_SITE_URL + _clean_path(path)


def _settings() -> dict:
    data = load("settings", default={})
    return data if isinstance(data, dict) else {}


def _static_seo(path: str) -> dict[str, Any]:
    settings = _settings()
    configured_pages = settings.get("seo_pages") if isinstance(settings.get("seo_pages"), dict) else {}
    fallback = STATIC_PAGE_FALLBACKS.get(path, {})

    for page in configured_pages.values():
        if isinstance(page, dict) and _clean_path(page.get("path", "")) == path:
            return {
                "title": page.get("title") or fallback.get("title") or DEFAULT_TITLE,
                "description": page.get("description") or fallback.get("description") or DEFAULT_DESCRIPTION,
                "image": page.get("image") or settings.get("seo_default_image") or fallback.get("image") or DEFAULT_IMAGE,
                "no_index": bool(page.get("no_index", False)),
                "type": "website",
            }

    return {
        "title": fallback.get("title") or DEFAULT_TITLE,
        "description": fallback.get("description") or DEFAULT_DESCRIPTION,
        "image": settings.get("seo_default_image") or fallback.get("image") or DEFAULT_IMAGE,
        "no_index": False,
        "type": "website",
    }


def _tour_seo(slug: str, path: str) -> dict[str, Any]:
    tour = get_by("tours", "slug", slug)
    if not tour or not tour.get("active", True):
        return {
            "title": "Тур не найден | TRAVELSPACE",
            "description": "Тур не найден.",
            "image": DEFAULT_IMAGE,
            "no_index": True,
            "type": "website",
        }

    image = tour.get("seo_image") or tour.get("og_image") or tour.get("hero_image")
    gallery = tour.get("gallery") if isinstance(tour.get("gallery"), list) else []
    if not image and gallery:
        image = gallery[0]

    description = (
        tour.get("seo_description")
        or tour.get("short_description")
        or tour.get("tagline")
        or tour.get("description")
        or f"{tour.get('title', 'Тур')}. Даты, программа, отели и стоимость тура."
    )

    structured = {
        "@context": "https://schema.org",
        "@type": "TouristTrip",
        "name": tour.get("title"),
        "description": _limit(description, 220),
        "url": _page_url(path),
        "image": _absolute_url(image),
    }
    if tour.get("price_from"):
        structured["offers"] = {
            "@type": "Offer",
            "price": str(tour.get("price_from")),
            "priceCurrency": tour.get("currency") or "BYN",
            "availability": "https://schema.org/InStock",
        }

    return {
        "title": tour.get("seo_title") or f"{tour.get('title', 'Тур')} | TRAVELSPACE",
        "description": description,
        "image": image,
        "no_index": False,
        "type": "article",
        "structured_data": structured,
    }


def _article_seo(slug: str, path: str) -> dict[str, Any]:
    article = get_by("articles", "slug", slug)
    if not article or not article.get("active", True):
        return {
            "title": "Статья не найдена | TRAVELSPACE",
            "description": "Статья не найдена.",
            "image": DEFAULT_IMAGE,
            "no_index": True,
            "type": "website",
        }

    description = article.get("seo_description") or article.get("excerpt") or article.get("content")
    image = article.get("seo_image") or article.get("cover") or DEFAULT_IMAGE
    structured = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.get("title"),
        "description": _limit(description, 220),
        "url": _page_url(path),
        "image": _absolute_url(image),
        "datePublished": article.get("published_at"),
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }

    return {
        "title": article.get("seo_title") or f"{article.get('title', 'Статья')} | TRAVELSPACE",
        "description": description,
        "image": image,
        "no_index": False,
        "type": "article",
        "structured_data": structured,
    }


def get_redirect_target(path: str) -> str | None:
    path = _clean_path(path)
    redirects = load("redirects", default=[])
    if not isinstance(redirects, list):
        return None
    for item in redirects:
        if not isinstance(item, dict):
            continue
        if _clean_path(item.get("from", "")) == path:
            target = item.get("to")
            return str(target) if target else None
    return None


def get_seo_for_path(path: str) -> dict[str, Any]:
    path = _clean_path(path)

    if path.startswith("/admin") or path.startswith("/api"):
        return {
            "title": "TRAVELSPACE",
            "description": DEFAULT_DESCRIPTION,
            "image": DEFAULT_IMAGE,
            "no_index": True,
            "type": "website",
        }

    if path.startswith("/tours/"):
        slug = path.split("/tours/", 1)[1].split("/", 1)[0]
        return _tour_seo(slug, path)

    if path.startswith("/blog/"):
        slug = path.split("/blog/", 1)[1].split("/", 1)[0]
        return _article_seo(slug, path)

    return _static_seo(path)


def _render_meta_block(path: str, seo: dict[str, Any]) -> str:
    title = _limit(seo.get("title") or DEFAULT_TITLE, 80)
    description = _limit(seo.get("description") or DEFAULT_DESCRIPTION, 180)
    image = _absolute_url(seo.get("image"))
    url = _page_url(path)
    robots = "noindex, nofollow" if seo.get("no_index") else "index, follow"
    og_type = seo.get("type") or "website"

    lines = [
        f"<title>{escape(title)}</title>",
        f'<meta name="description" content="{escape(description)}" />',
        f'<meta name="robots" content="{robots}" />',
        f'<link rel="canonical" href="{escape(url)}" />',
        f'<meta property="og:type" content="{escape(og_type)}" />',
        f'<meta property="og:site_name" content="{SITE_NAME}" />',
        '<meta property="og:locale" content="ru_RU" />',
        f'<meta property="og:title" content="{escape(title)}" />',
        f'<meta property="og:description" content="{escape(description)}" />',
        f'<meta property="og:url" content="{escape(url)}" />',
        f'<meta property="og:image" content="{escape(image)}" />',
        f'<meta property="og:image:secure_url" content="{escape(image)}" />',
        '<meta property="og:image:width" content="1200" />',
        '<meta property="og:image:height" content="630" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{escape(title)}" />',
        f'<meta name="twitter:description" content="{escape(description)}" />',
        f'<meta name="twitter:image" content="{escape(image)}" />',
    ]

    structured = seo.get("structured_data")
    if structured:
        import json

        lines.append(
            '<script type="application/ld+json">'
            + json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
            + "</script>"
        )

    return "\n    " + "\n    ".join(lines) + "\n"


def render_index_html(path: str) -> str:
    if not INDEX_HTML_PATH.exists():
        return ""

    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    for pattern in SEO_TAG_PATTERNS:
        html = re.sub(pattern, "", html, flags=re.IGNORECASE | re.DOTALL)

    seo = get_seo_for_path(path)
    meta_block = _render_meta_block(path, seo)
    return re.sub(r"<head>", "<head>" + meta_block, html, count=1, flags=re.IGNORECASE)


def build_sitemap_xml() -> str:
    urls: list[str] = []
    static_paths = list(STATIC_PAGE_FALLBACKS.keys())
    urls.extend(static_paths)

    for tour in list_items("tours"):
        if tour.get("active", True) and tour.get("slug"):
            urls.append(f"/tours/{tour['slug']}")

    for article in list_items("articles"):
        if article.get("active", True) and article.get("slug"):
            urls.append(f"/blog/{article['slug']}")

    unique_urls = []
    seen = set()
    for path in urls:
        clean = _clean_path(path)
        if clean not in seen:
            seen.add(clean)
            unique_urls.append(clean)

    now = datetime.now(timezone.utc).date().isoformat()
    entries = "\n".join(
        "  <url>\n"
        f"    <loc>{escape(_page_url(path))}</loc>\n"
        f"    <lastmod>{now}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "  </url>"
        for path in unique_urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entries}\n</urlset>\n'


def build_robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /api/admin\n"
        "Disallow: /api/auth\n"
        f"Sitemap: {PUBLIC_SITE_URL}/sitemap.xml\n"
    )
