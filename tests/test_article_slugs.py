import asyncio

import pytest

import seo_runtime
import server
import storage
from article_slugs import migrate_article_slugs


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.save("settings", {})
    storage.save("articles", [])
    yield tmp_path


def test_migration_replaces_underscores_and_preserves_redirect_history():
    articles = [
        {
            "slug": "teriberka_v_murmanske",
            "seo_canonical_url": "https://travelspace.by/blog/teriberka_v_murmanske",
        }
    ]
    assert migrate_article_slugs(articles) is True
    assert articles[0]["slug"] == "teriberka-v-murmanske"
    assert articles[0]["legacy_slugs"] == ["teriberka_v_murmanske"]
    assert articles[0]["seo_canonical_url"] == "https://travelspace.by/blog/teriberka-v-murmanske"
    assert migrate_article_slugs(articles) is False


def test_all_reported_underscore_urls_receive_clean_targets():
    old_slugs = [
        "teriberka_v_murmanske",
        "carskoe_selo_v_pitere",
        "park_ruskeala_v_karelii",
        "severnoe_siyanie_v_murmanske",
    ]
    articles = [{"slug": slug} for slug in old_slugs]
    assert migrate_article_slugs(articles) is True
    assert [article["slug"] for article in articles] == [
        "teriberka-v-murmanske",
        "carskoe-selo-v-pitere",
        "park-ruskeala-v-karelii",
        "severnoe-siyanie-v-murmanske",
    ]


def test_article_crud_normalizes_new_slugs_and_redirects_old_urls(isolated):
    created = server._crud_create(
        "articles",
        {"title": "Териберка", "slug": "teriberka_v_murmanske", "active": True},
    )
    assert created["slug"] == "teriberka-v-murmanske"
    assert created["legacy_slugs"] == ["teriberka_v_murmanske"]
    assert seo_runtime.get_redirect_target("/blog/teriberka_v_murmanske") == "/blog/teriberka-v-murmanske"
    response = asyncio.run(server.serve_react_app("blog/teriberka_v_murmanske"))
    assert response.status_code == 301
    assert response.headers["location"] == "/blog/teriberka-v-murmanske"
    assert seo_runtime.get_http_status_for_path("/blog/teriberka-v-murmanske") == 200
    assert "https://travelspace.by/blog/teriberka-v-murmanske" in seo_runtime.build_sitemap_xml()


def test_changing_article_slug_keeps_previous_address(isolated):
    created = server._crud_create(
        "articles",
        {"title": "Статья", "slug": "first-address", "active": True},
    )
    updated = server._crud_update(
        "articles", created["id"], {"slug": "second_address"}
    )
    assert updated["slug"] == "second-address"
    assert updated["legacy_slugs"] == ["second_address", "first-address"]
    assert seo_runtime.get_redirect_target("/blog/first-address") == "/blog/second-address"
    assert seo_runtime.get_redirect_target("/blog/second_address") == "/blog/second-address"
