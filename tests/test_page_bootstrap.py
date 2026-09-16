"""Synthetic storage only: these tests never start the app or submit leads."""
import json
import re

import pytest
import seo_runtime
from tests.test_seo_runtime import configure_storage, TOURS, ARTICLES, SETTINGS


@pytest.fixture
def render(monkeypatch, tmp_path):
    configure_storage(monkeypatch)
    template = tmp_path / "index.html"
    template.write_text(
        '<!doctype html><html><head><title>SPA</title></head><body>'
        '<noscript>You need to enable JavaScript to run this app.</noscript>'
        '<div id="initial-load-cover" aria-hidden="true"></div>'
        '<div id="root"></div><script defer src="/static/js/main.js"></script>'
        '</body></html>', encoding="utf-8",
    )
    monkeypatch.setattr(seo_runtime, "INDEX_HTML_PATH", template)
    return seo_runtime.render_index_html


def bootstrap(document):
    match = re.search(r'<script id="page-bootstrap" type="application/json">(.*?)</script>', document, re.S)
    assert match
    return json.loads(match[1])


@pytest.mark.parametrize("path,slug,status,noindex", [
    ("/tours/public-tour", "public-tour", 200, False),
    ("/tours/hidden-tour", "hidden-tour", 200, False),
    ("/tours/noindex-tour", "noindex-tour", 200, True),
    ("/tours/inactive-tour", None, 404, True),
    ("/tours/missing-tour", None, 404, True),
    ("/blog/public-article", "public-article", 200, False),
    ("/blog/hidden-article", "hidden-article", 200, False),
    ("/blog/inactive-article", None, 404, True),
])
def test_publication_and_metadata_match_initial_document(render, path, slug, status, noindex):
    document = render(path)
    data = bootstrap(document)
    assert data["path"] == path
    assert data["status"] == status
    assert (data["record"] or {}).get("slug") == slug
    assert data["seo"]["noIndex"] is noindex
    robots = "noindex" if noindex else "index"
    assert f'name="robots" content="{robots}, follow"' in document
    assert document.count("<title") == 1
    assert document.count('name="description"') == 1
    assert document.count('rel="canonical"') == 1
    assert data["seo"]["description"]
    assert "Загрузка тура" not in document


def test_full_record_and_readable_content_exist_without_javascript(render):
    document = render("/tours/public-tour")
    data = bootstrap(document)
    assert data["record"]["program"] == TOURS[0]["program"]
    assert data["record"]["dates"] == TOURS[0]["dates"]
    assert data["record"]["included"] == TOURS[0]["included"]
    assert '<h1>Тур в Грузию</h1>' in document
    assert 'Полное описание дня 6.' in document
    assert 'id="initial-load-cover"' not in document
    assert 'You need to enable JavaScript' not in document
    assert 'id="server-page-style"' in document


def test_tour_advertising_anchors_are_preserved_in_bootstrap_and_snapshot(
    render, monkeypatch
):
    monkeypatch.setitem(
        TOURS[0],
        "section_anchors",
        {"program": "route-plan", "dates": "sale-dates"},
    )
    monkeypatch.setitem(
        TOURS[0],
        "program",
        [
            {**day, "anchor": "first-day" if index == 0 else ""}
            for index, day in enumerate(TOURS[0]["program"])
        ],
    )

    document = render("/tours/public-tour")
    data = bootstrap(document)

    assert data["record"]["section_anchors"] == {
        "program": "route-plan",
        "dates": "sale-dates",
    }
    assert data["record"]["program"][0]["anchor"] == "first-day"
    assert 'id="program"' in document
    assert 'id="route-plan"' in document
    assert 'id="sale-dates"' in document
    assert '<section id="first-day">' in document


def test_bootstrap_excludes_private_fields_and_unlisted_cards(render, monkeypatch):
    monkeypatch.setitem(TOURS[0], "internal_notes", "private tour notes")
    monkeypatch.setitem(SETTINGS, "telegram_bot_token", "private bot token")
    data = bootstrap(render("/tours/hidden-tour"))
    assert data["record"]["slug"] == "hidden-tour"
    assert "hidden-tour" not in [item["slug"] for item in data["site"]["tours"]]
    assert "inactive-tour" not in [item["slug"] for item in data["site"]["tours"]]
    assert "hidden-article" not in [item["slug"] for item in data["site"]["articles"]]
    assert "private" not in json.dumps(data)
    assert data["site"]["articles"][0]["excerpt"] == ARTICLES[0]["content"]


def test_home_bootstrap_keeps_only_first_screen_collections_and_hub_labels(render, monkeypatch):
    monkeypatch.setitem(SETTINGS, "seo_pages", {"home": {"title": "Главная"}, "reviews": {"title": "Отзывы"}})
    monkeypatch.setitem(
        SETTINGS,
        "seo_hubs",
        {
            "custom-direction": {
                "custom": True,
                "label": "Новое направление",
                "heading": "Новое направление",
                "content_body": "Большой текст посадочной страницы " * 500,
            }
        },
    )

    data = bootstrap(render("/"))

    assert len(data["collections"]["reviews"]) == 1
    assert len(data["collections"]["promotions"]) == 1
    assert [item["id"] for item in data["collections"]["faq"]] == ["faq-home"]
    assert data["site"]["settings"]["seo_hubs"]["custom-direction"] == {
        "custom": True,
        "label": "Новое направление",
        "heading": "Новое направление",
    }
    assert list(data["site"]["settings"]["seo_pages"]) == ["home"]


def test_marketing_ids_are_available_to_the_frontend_bootstrap(render, monkeypatch):
    expected = {
        "gtm_id": "GTM-THKV9X9D",
        "google_analytics_id": "G-RFW4TK6SCS",
        "yandex_metrika_id": "112563125",
        "facebook_pixel_id": "1234567890",
        "tiktok_pixel_id": "C123456789",
    }
    for key, value in expected.items():
        monkeypatch.setitem(SETTINGS, key, value)

    data = bootstrap(render("/"))

    for key, value in expected.items():
        assert data["site"]["settings"][key] == value


def test_gtm_is_present_in_source_html_on_all_public_pages(render, monkeypatch):
    monkeypatch.setitem(SETTINGS, "gtm_id", "GTM-THKV9X9D")

    for path in ("/", "/tours/public-tour", "/blog/public-article"):
        document = render(path)
        # Head loader, body noscript fallback, and the React bootstrap settings.
        assert document.count("GTM-THKV9X9D") == 3
        assert "https://www.googletagmanager.com/gtm.js?id=" in document
        assert "https://www.googletagmanager.com/ns.html?id=GTM-THKV9X9D" in document
        assert document.index('data-server-gtm="true"') < document.index("</head>")


def test_gtm_is_not_injected_for_invalid_id_or_admin(render, monkeypatch):
    monkeypatch.setitem(SETTINGS, "gtm_id", 'GTM-BAD\"><script>alert(1)</script>')
    assert "googletagmanager.com" not in render("/")

    monkeypatch.setitem(SETTINGS, "gtm_id", "GTM-THKV9X9D")
    assert "googletagmanager.com" not in render("/admin/settings")


def test_script_content_cannot_escape_json_element(render, monkeypatch):
    malicious = '</script><script>alert("x")</script> & \u2028 \u2029'
    monkeypatch.setitem(TOURS[0], "description", malicious)
    document = render("/tours/public-tour")
    assert bootstrap(document)["record"]["description"] == malicious
    assert '<script>alert(' not in document
    assert document.count('id="page-bootstrap"') == 1


def test_home_styles_and_route_chunk_are_available_in_initial_document(render, monkeypatch, tmp_path):
    build = tmp_path / "build"
    css = build / "static" / "css" / "main.test.css"
    css.parent.mkdir(parents=True)
    css.write_text('.home-hero{min-height:100vh;color:white}', encoding="utf-8")
    (build / "asset-manifest.json").write_text(json.dumps({"files": {
        "static/js/home.123abc.chunk.js": "/static/js/home.123abc.chunk.js",
        "static/js/admin.123abc.chunk.js": "/static/js/admin.123abc.chunk.js",
    }}), encoding="utf-8")
    monkeypatch.setattr(seo_runtime, "FRONTEND_BUILD_DIR", build)
    template = seo_runtime.INDEX_HTML_PATH
    template.write_text('<html><head><link href="/static/css/main.test.css" rel="stylesheet"></head>'
                        '<body><div id="root"></div></body></html>', encoding="utf-8")

    home = render("/")
    assert '<style id="home-critical-style">' in home
    assert 'html,body{margin:0;background:#0a0906' not in home
    assert '<link rel="preload" as="style" href="/static/css/main.test.css"' in home
    assert '<noscript><link rel="stylesheet" href="/static/css/main.test.css"></noscript>' in home
    assert '<link rel="preload" as="script" href="/static/js/home.123abc.chunk.js">' in home
    assert 'admin.123abc' not in home
    assert 'class="home-hero"' in home
    assert home.count('<h1>') == 1
    assert 'id="avtobusnie-tury"' in home
    assert '<link href="/static/css/main.test.css" rel="stylesheet">' not in home
    other_page = render('/reviews')
    assert '<link href="/static/css/main.test.css" rel="stylesheet">' in other_page
    assert 'home-critical-style' not in other_page


def test_missing_build_stylesheet_keeps_original_link(render):
    template = '<head><link href="/static/css/missing.css" rel="stylesheet"></head>'
    assert '<link href="/static/css/missing.css" rel="stylesheet">' in seo_runtime._home_render_assets(template)


def test_blank_metadata_falls_back_to_real_text(render, monkeypatch):
    monkeypatch.setitem(TOURS[0], "seo_description", "  <b> </b> ** ")
    monkeypatch.setitem(TOURS[0], "seo_title", "   ")
    data = bootstrap(render("/tours/public-tour"))
    assert data["seo"]["description"] == "Большая программа тура."
    assert data["seo"]["title"] == "Тур в Грузию | TRAVELSPACE"


@pytest.mark.parametrize("path", ["/admin", "/admin/", "/admin/login", "/admin/tours", "/admin/settings"])
def test_admin_does_not_receive_public_bootstrap_or_snapshot(render, path):
    document = render(path)
    assert 'id="page-bootstrap"' not in document
    assert 'data-seo-prerender' not in document
    assert '<div id="root"></div>' in document
    assert 'name="robots" content="noindex, follow"' in document
    assert seo_runtime.get_http_status_for_path(path) == 200
