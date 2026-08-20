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
        "updated_at": "2026-08-05T08:30:00+00:00",
    },
    {
        "slug": "hidden-tour",
        "title": "Скрытый тур",
        "active": True,
        "hidden": True,
    },
]

ARTICLES = [
    {
        "slug": "public-article",
        "title": "Статья о Грузии",
        "active": True,
        "content": "Полезный текст.",
        "published_at": "2026-08-01",
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
    assert "<h1>Тур в Грузию</h1>" in html
    assert "Большая программа тура" in html


def test_status_and_indexability_are_consistent(monkeypatch):
    configure_storage(monkeypatch)

    assert seo_runtime.get_http_status_for_path("/tours/public-tour") == 200
    assert seo_runtime.get_http_status_for_path("/tours/hidden-tour") == 404
    assert seo_runtime.get_http_status_for_path("/does-not-exist") == 404
    assert seo_runtime.get_seo_for_path("/thanks")["no_index"] is True
    assert seo_runtime.get_seo_for_path("/does-not-exist")["no_index"] is True


def test_sitemap_contains_only_public_canonical_urls(monkeypatch):
    configure_storage(monkeypatch)

    sitemap = seo_runtime.build_sitemap_xml()

    assert "https://travelspace.by/tours/public-tour" in sitemap
    assert "https://travelspace.by/tours/hidden-tour" not in sitemap
    assert "https://travelspace.by/tours/gruziya" in sitemap
    assert "<lastmod>2026-08-05</lastmod>" in sitemap
    assert "changefreq" not in sitemap


def test_legacy_direction_has_permanent_destination(monkeypatch):
    configure_storage(monkeypatch)
    assert (
        seo_runtime.get_redirect_target("/directions/saint-petersburg")
        == "/tours/sankt-peterburg"
    )
