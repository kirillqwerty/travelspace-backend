"""Visa pages stay independent, editable, and consistent with SEO routes."""

import pytest
from fastapi.testclient import TestClient

import seo_runtime
import server
import storage
import visas


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(visas, "DATA_DIR", tmp_path)
    template = tmp_path / "index.html"
    template.write_text('<html><head><title>Test</title></head><body><div id="root"></div></body></html>', encoding="utf-8")
    monkeypatch.setattr(seo_runtime, "INDEX_HTML_PATH", template)
    storage.save("settings", {})
    visas.ensure_visa_seed()
    server.app.dependency_overrides[server.get_current_admin] = lambda: {"email": "test@example.invalid"}
    yield TestClient(server.app)
    server.app.dependency_overrides.pop(server.get_current_admin, None)


def test_seed_is_five_eu_examples_and_keeps_edits(client):
    records = client.get("/api/visa").json()
    assert len(records) == 5
    assert {record["country_code"] for record in records} == {"FR", "DE", "IT", "ES", "PL"}
    original = records[0]
    changed = {**original, "title": "Изменённый заголовок"}
    assert client.put(f"/api/admin/visa/{original['id']}", json=changed).status_code == 200
    visas.ensure_visa_seed()
    assert client.get(f"/api/visa/{original['slug']}").json()["title"] == "Изменённый заголовок"


def test_admin_validation_visibility_redirect_and_sitemap(client):
    assert client.post("/api/admin/visa", json={"country_code": "US", "slug": "usa", "title": "USA"}).status_code == 422
    assert client.post("/api/admin/visa", json={"country_code": "FR", "slug": "france", "title": "Дубликат"}).status_code == 422
    record = client.get("/api/visa/france").json()
    changed = {**record, "slug": "france-visa", "seo_noindex": True}
    assert client.put(f"/api/admin/visa/{record['id']}", json=changed).status_code == 200
    assert seo_runtime.get_redirect_target("/visa/france") == "/visa/france-visa"
    assert seo_runtime.get_redirect_target("/visas/france") == "/visa/france-visa"
    assert seo_runtime.get_http_status_for_path("/visa/france-visa") == 200
    assert "/visa/france-visa" not in seo_runtime.build_sitemap_xml()
    assert seo_runtime.get_seo_for_path("/visa/france-visa")["no_index"] is True
    changed["active"] = False
    assert client.put(f"/api/admin/visa/{record['id']}", json=changed).status_code == 200
    assert client.get("/api/visa/france-visa").status_code == 404
    assert seo_runtime.get_http_status_for_path("/visa/france-visa") == 404


def test_editable_landing_and_server_snapshot(client):
    page = client.get("/api/admin/visa-page").json()["page"]
    page["title"] = "Новый заголовок виз"
    page["steps"] = [{"title": "Связаться", "text": "Оставить контакты"}]
    assert client.put("/api/admin/visa-page", json=page).status_code == 200
    assert seo_runtime.get_seo_for_path("/visa")["heading"] == "Новый заголовок виз"
    html = seo_runtime.render_index_html("/visa")
    assert "Новый заголовок виз" in html
    assert "Оставить контакты" in html
    assert "france" in html


def test_demand_counter_only_counts_visa_inquiries(client):
    storage.save("leads", [
        {"id": "one", "form_type": "visa", "region": "Франция"},
        {"id": "two", "form_type": "visa", "region": "Франция"},
        {"id": "three", "form_type": "visa", "region": "Визы ЕС"},
        {"id": "four", "form_type": "tour", "region": "Франция"},
    ])
    assert client.get("/api/admin/visa-demand").json() == {
        "total": 3, "general": 1, "by_country": {"Франция": 2},
    }


def test_old_public_urls_redirect_to_singular_paths(client):
    listing = client.get("/visas", follow_redirects=False)
    detail = client.get("/visas/france?utm_source=test", follow_redirects=False)
    assert (listing.status_code, listing.headers["location"]) == (301, "/visa")
    assert (detail.status_code, detail.headers["location"]) == (301, "/visa/france?utm_source=test")
    assert client.get("/visa").status_code == 200
    assert client.get("/visa/france").status_code == 200
    sitemap = seo_runtime.build_sitemap_xml()
    assert "/visa/france" in sitemap
    assert "/visas/france" not in sitemap
