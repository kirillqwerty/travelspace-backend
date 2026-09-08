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


def test_script_content_cannot_escape_json_element(render, monkeypatch):
    malicious = '</script><script>alert("x")</script> & \u2028 \u2029'
    monkeypatch.setitem(TOURS[0], "description", malicious)
    document = render("/tours/public-tour")
    assert bootstrap(document)["record"]["description"] == malicious
    assert '<script>alert(' not in document
    assert document.count('id="page-bootstrap"') == 1


def test_blank_metadata_falls_back_to_real_text(render, monkeypatch):
    monkeypatch.setitem(TOURS[0], "seo_description", "  <b> </b> ** ")
    monkeypatch.setitem(TOURS[0], "seo_title", "   ")
    data = bootstrap(render("/tours/public-tour"))
    assert data["seo"]["description"] == "Большая программа тура."
    assert data["seo"]["title"] == "Тур в Грузию | TRAVELSPACE"


def test_admin_does_not_receive_public_bootstrap(render):
    assert 'id="page-bootstrap"' not in render("/admin/login")
