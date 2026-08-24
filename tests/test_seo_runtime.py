from pathlib import Path

import seo_runtime


TOURS = [
    {
        "slug": "public-tour",
        "title": "Тур в Грузию",
        "active": True,
        "hidden": False,
        "description": "Большая программа тура.",
        "region_name": "Грузия",
        "seo_h1": "Автобусный тур в Грузию из Минска",
        "price_from": 1200,
        "currency": "BYN",
        "program": [
            {"day": str(day), "title": f"Маршрут {day}", "description": f"Полное описание дня {day}."}
            for day in range(1, 7)
        ],
        "included": ["Проезд", "Проживание"],
        "excluded": ["Личные расходы"],
        "important_info": ["Возьмите паспорт"],
        "dates": [{"id": "date-1", "start": "2026-09-01", "end": "2026-09-07", "price": 1250, "currency": "BYN"}],
        "faq": [{"question": "Нужен ли паспорт?", "answer": "Да, документ нужен."}],
        "updated_at": "2026-08-05T08:30:00+00:00",
    },
    {
        "slug": "hidden-tour",
        "title": "Скрытый тур",
        "active": True,
        "hidden": True,
    },
    {
        "slug": "noindex-tour",
        "title": "Закрытый от поиска тур",
        "active": True,
        "seo_noindex": True,
    },
    {
        "slug": "canonical-copy",
        "title": "Копия тура",
        "active": True,
        "seo_canonical_url": "/tours/public-tour",
    },
]

ARTICLES = [
    {
        "slug": "public-article",
        "title": "Статья о Грузии",
        "active": True,
        "content": "Полезный текст.",
        "published_at": "2026-08-01",
        "seo_lastmod": "18.08.2026",
    }
]


def configure_storage(monkeypatch):
    def list_items(name):
        return TOURS if name == "tours" else ARTICLES if name == "articles" else []

    def get_by(name, key, value):
        return next((item for item in list_items(name) if item.get(key) == value), None)

    monkeypatch.setattr(seo_runtime, "list_items", list_items)
    monkeypatch.setattr(seo_runtime, "get_by", get_by)
    monkeypatch.setattr(seo_runtime, "load", lambda name, default=None: {} if name == "settings" else default)


def test_rendered_page_has_one_metadata_set_and_semantic_snapshot(tmp_path, monkeypatch):
    configure_storage(monkeypatch)
    index_path = Path(tmp_path) / "index.html"
    index_path.write_text(
        '<!doctype html><html><head><title>SPA</title><meta name="description" content="old"></head>'
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(seo_runtime, "INDEX_HTML_PATH", index_path)

    html = seo_runtime.render_index_html("/tours/public-tour")

    assert html.count("<title") == 1
    assert html.count('name="description"') == 1
    assert html.count('rel="canonical"') == 1
    assert html.count("application/ld+json") == 1
    assert 'data-rh="true"' in html
    assert 'data-seo-prerender="true"' in html
    assert "<h1>Автобусный тур в Грузию из Минска</h1>" in html
    assert "Большая программа тура" in html
    assert "<h3>День 6 — Маршрут 6</h3>" in html
    assert "Полное описание дня 6." in html
    assert "Личные расходы" in html
    assert "Возьмите паспорт" in html
    assert "Нужен ли паспорт?" in html
    assert "2026-09-01 — 2026-09-07: 1250 BYN" in html


def test_status_and_indexability_are_consistent(monkeypatch):
    configure_storage(monkeypatch)

    assert seo_runtime.get_http_status_for_path("/tours/public-tour") == 200
    assert seo_runtime.get_http_status_for_path("/tours/hidden-tour") == 404
    assert seo_runtime.get_http_status_for_path("/tours/noindex-tour") == 200
    assert seo_runtime.get_http_status_for_path("/does-not-exist") == 404
    assert seo_runtime.get_seo_for_path("/thanks")["no_index"] is True
    assert seo_runtime.get_seo_for_path("/does-not-exist")["no_index"] is True


def test_sitemap_contains_only_public_canonical_urls(monkeypatch):
    configure_storage(monkeypatch)

    sitemap = seo_runtime.build_sitemap_xml()

    assert "https://travelspace.by/tours/public-tour" in sitemap
    assert "https://travelspace.by/tours/hidden-tour" not in sitemap
    assert "https://travelspace.by/tours/noindex-tour" not in sitemap
    assert "https://travelspace.by/tours/canonical-copy" not in sitemap
    assert "https://travelspace.by/tours/gruziya" in sitemap
    assert "<lastmod>2026-08-05</lastmod>" in sitemap
    assert "<lastmod>2026-08-18</lastmod>" in sitemap
    assert "changefreq" not in sitemap


def test_legacy_direction_has_permanent_destination(monkeypatch):
    configure_storage(monkeypatch)
    assert (
        seo_runtime.get_redirect_target("/directions/saint-petersburg")
        == "/tours/sankt-peterburg"
    )


def test_canonical_and_robots_overrides_are_safe(monkeypatch):
    configure_storage(monkeypatch)

    canonical_copy = seo_runtime.get_seo_for_path("/tours/canonical-copy")
    assert canonical_copy["canonical_url"] == "https://travelspace.by/tours/public-tour"

    noindex = seo_runtime.get_seo_for_path("/tours/noindex-tour")
    meta = seo_runtime._render_meta_block("/tours/noindex-tour", noindex)
    assert 'name="robots" content="noindex, follow"' in meta

    assert (
        seo_runtime.canonical_url_for_path(
            "https://example.com/stolen", "/tours/public-tour"
        )
        == "https://travelspace.by/tours/public-tour"
    )
    assert (
        seo_runtime.canonical_url_for_path(
            "/does-not-exist", "/tours/public-tour"
        )
        == "https://travelspace.by/tours/public-tour"
    )
