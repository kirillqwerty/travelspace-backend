"""Backend regression tests for tour operator API (JSON storage).

Covers public endpoints, lead validation, JWT auth, admin CRUD.
NOTE: "directions" entity has been REMOVED. All endpoints below must
reflect this — there is no /api/directions or /api/admin/directions.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "admin123"

TOUR_SLUGS = [
    "dagestan-7-dney",
    "gruziya-kobuleti-10-dney",
    "saint-petersburg-5-dney",
    "kareliya-5-dney",
    "dagestan-mini-5-dney",
]
REGION_SLUGS = {"georgia-kobuleti", "dagestan", "saint-petersburg", "kareliya"}


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(client):
    r = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and "user" in data
    assert data["user"]["email"] == ADMIN_EMAIL
    return data["token"]


@pytest.fixture()
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Public endpoints ----------

class TestPublic:
    def test_root(self, client):
        r = client.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_settings(self, client):
        r = client.get(f"{API}/settings")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_tours_list(self, client):
        r = client.get(f"{API}/tours")
        assert r.status_code == 200
        tours = r.json()
        assert isinstance(tours, list)
        assert len(tours) == 5, f"expected 5 tours, got {len(tours)}"
        for t in tours:
            # region_* present, direction_* absent
            assert "region_slug" in t and t["region_slug"] in REGION_SLUGS
            assert "region_name" in t
            assert "direction_slug" not in t, f"tour {t.get('slug')} still has direction_slug"
            assert "direction_name" not in t, f"tour {t.get('slug')} still has direction_name"
            # Enriched fields (moved from directions)
            for field in ("tagline", "description", "hero_image", "gallery",
                          "highlights", "what_to_see", "dates", "faq"):
                assert field in t, f"tour {t.get('slug')} missing field {field}"

    @pytest.mark.parametrize("slug", TOUR_SLUGS)
    def test_tour_detail(self, client, slug):
        r = client.get(f"{API}/tours/{slug}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("slug") == slug
        assert body.get("region_slug") in REGION_SLUGS

    def test_tour_not_found(self, client):
        r = client.get(f"{API}/tours/non-existent-xyz")
        assert r.status_code == 404

    def test_tours_filter_by_region(self, client):
        r = client.get(f"{API}/tours", params={"region": "dagestan"})
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        assert all(t.get("region_slug") == "dagestan" for t in items)

    def test_tours_filter_by_badge(self, client):
        r = client.get(f"{API}/tours", params={"badge": "Хит"})
        assert r.status_code == 200
        items = r.json()
        for t in items:
            assert "Хит" in (t.get("badges") or [])

    # --- directions must be GONE ---
    def test_directions_list_removed(self, client):
        r = client.get(f"{API}/directions")
        assert r.status_code == 404, f"/api/directions still exists: {r.status_code}"

    def test_direction_detail_removed(self, client):
        r = client.get(f"{API}/directions/dagestan")
        assert r.status_code == 404, f"/api/directions/dagestan still exists: {r.status_code}"

    def test_admin_directions_removed(self, client, auth_headers):
        r = client.get(f"{API}/admin/directions", headers=auth_headers)
        assert r.status_code == 404, f"/api/admin/directions still exists: {r.status_code}"

    # --- specialists ---
    def test_specialists(self, client):
        r = client.get(f"{API}/specialists")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list) and len(items) > 0
        for s in items:
            regions = s.get("regions") or []
            # all regions should be region_slug values (not direction_slug)
            for region in regions:
                assert region in REGION_SLUGS, f"specialist '{s.get('name')}' has bad region '{region}'"

    def test_specialists_filter_by_region(self, client):
        r = client.get(f"{API}/specialists", params={"region": "dagestan"})
        assert r.status_code == 200
        items = r.json()
        for s in items:
            assert "dagestan" in (s.get("regions") or [])

    @pytest.mark.parametrize("path", ["/reviews", "/promotions", "/faq", "/articles"])
    def test_simple_collections(self, client, path):
        r = client.get(f"{API}{path}")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) > 0, f"{path} empty"

    def test_article_detail(self, client):
        listing = client.get(f"{API}/articles").json()
        slug = listing[0]["slug"]
        r = client.get(f"{API}/articles/{slug}")
        assert r.status_code == 200
        assert r.json().get("slug") == slug


# ---------- Leads ----------

class TestLeads:
    created_id: str | None = None

    def test_create_lead_ok(self, client):
        payload = {
            "name": "TEST_User",
            "phone": "+375 29 123-45-67",
            "tour": "Дагестан 7 дней",
            "tour_slug": "dagestan-7-dney",
            "region": "dagestan",
            "consent": True,
            "comment": "TEST_lead",
        }
        r = client.post(f"{API}/leads", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "id" in body
        TestLeads.created_id = body["id"]

    def test_create_lead_consent_false(self, client):
        r = client.post(f"{API}/leads", json={"phone": "+375 29 123-45-67", "consent": False})
        assert r.status_code == 422

    def test_create_lead_bad_phone(self, client):
        r = client.post(f"{API}/leads", json={"phone": "12345", "consent": True})
        assert r.status_code == 422

    def test_admin_leads_unauthorized(self, client):
        r = client.get(f"{API}/admin/leads/list")
        assert r.status_code == 401

    def test_admin_leads_list_and_status(self, client, auth_headers):
        r = client.get(f"{API}/admin/leads/list", headers=auth_headers)
        assert r.status_code == 200
        leads = r.json()
        assert isinstance(leads, list)
        lead_id = TestLeads.created_id
        assert lead_id is not None
        # verify our lead exists with region/tour fields
        found = next((x for x in leads if x["id"] == lead_id), None)
        assert found is not None
        assert found.get("tour_slug") == "dagestan-7-dney"
        assert found.get("region") == "dagestan"
        # PATCH status
        r2 = client.patch(f"{API}/admin/leads/{lead_id}", headers=auth_headers,
                          json={"status": "in_progress"})
        assert r2.status_code == 200
        assert r2.json().get("status") == "in_progress"
        # DELETE
        r4 = client.delete(f"{API}/admin/leads/{lead_id}", headers=auth_headers)
        assert r4.status_code == 200


# ---------- Auth ----------

class TestAuth:
    def test_login_wrong_password(self, client):
        r = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_no_token(self, client):
        r = client.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, client, auth_headers):
        r = client.get(f"{API}/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("email") == ADMIN_EMAIL

    def test_me_bad_token(self, client):
        r = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-token"})
        assert r.status_code == 401


# ---------- Admin CRUD ----------

@pytest.mark.parametrize("collection,payload,update_field", [
    ("faq", {"question": "TEST_q", "answer": "TEST_a", "order": 999}, "question"),
    ("reviews", {"author": "TEST_author", "text": "TEST_text", "order": 999}, "author"),
    ("promotions", {"title": "TEST_promo", "description": "TEST_desc"}, "title"),
])
def test_admin_collection_crud(client, auth_headers, collection, payload, update_field):
    r = client.post(f"{API}/admin/{collection}", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    item_id = r.json()["id"]
    r2 = client.get(f"{API}/admin/{collection}", headers=auth_headers)
    assert any(x["id"] == item_id for x in r2.json())
    r3 = client.put(f"{API}/admin/{collection}/{item_id}", headers=auth_headers,
                    json={update_field: "TEST_updated"})
    assert r3.status_code == 200
    assert r3.json()[update_field] == "TEST_updated"
    r4 = client.delete(f"{API}/admin/{collection}/{item_id}", headers=auth_headers)
    assert r4.status_code == 200
    r5 = client.get(f"{API}/admin/{collection}", headers=auth_headers)
    assert all(x["id"] != item_id for x in r5.json())


def test_admin_tours_full_crud(client, auth_headers):
    """Admin can CRUD a tour with extended fields (highlights, what_to_see, gallery, faq, dates)."""
    payload = {
        "title": "TEST_Tour",
        "slug": f"test-tour-{uuid.uuid4().hex[:8]}",
        "tagline": "TEST_tagline",
        "region_slug": "dagestan",
        "region_name": "Дагестан",
        "duration": "7 дней",
        "price_from": 1000,
        "hero_image": "https://example.com/img.jpg",
        "description": "TEST_description",
        "highlights": ["h1", "h2"],
        "what_to_see": ["w1"],
        "gallery": ["https://example.com/1.jpg"],
        "faq": [{"q": "Q", "a": "A"}],
        "hotels": [{"name": "Hotel"}],
        "program": [{"day": 1, "title": "Day 1"}],
        "dates": [{"date": "2026-05-01", "price": 1200}],
        "badges": ["Хит"],
        "order": 999,
    }
    r = client.post(f"{API}/admin/tours", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    tour_id = r.json()["id"]
    # verify persistence + extended fields
    r2 = client.get(f"{API}/tours/{payload['slug']}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["highlights"] == ["h1", "h2"]
    assert body["dates"] == [{"date": "2026-05-01", "price": 1200}]
    assert body["faq"] == [{"q": "Q", "a": "A"}]
    # update
    r3 = client.put(f"{API}/admin/tours/{tour_id}", headers=auth_headers,
                    json={"tagline": "TEST_updated_tagline"})
    assert r3.status_code == 200
    assert r3.json()["tagline"] == "TEST_updated_tagline"
    # delete
    r4 = client.delete(f"{API}/admin/tours/{tour_id}", headers=auth_headers)
    assert r4.status_code == 200
    r5 = client.get(f"{API}/tours/{payload['slug']}")
    assert r5.status_code == 404


def test_admin_unknown_collection(client, auth_headers):
    r = client.get(f"{API}/admin/unknown_xyz", headers=auth_headers)
    assert r.status_code == 404


def test_admin_directions_collection_removed(client, auth_headers):
    """Verify admin CRUD for 'directions' is rejected."""
    r = client.get(f"{API}/admin/directions", headers=auth_headers)
    assert r.status_code == 404
    r2 = client.post(f"{API}/admin/directions", headers=auth_headers, json={"slug": "test"})
    assert r2.status_code == 404


def test_admin_settings_get_put(client, auth_headers):
    r = client.get(f"{API}/admin/settings", headers=auth_headers)
    assert r.status_code == 200
    original = r.json()
    new_settings = {**original, "test_marker": f"TEST_{uuid.uuid4().hex[:8]}"}
    r2 = client.put(f"{API}/admin/settings", headers=auth_headers, json=new_settings)
    assert r2.status_code == 200
    r3 = client.get(f"{API}/settings")
    assert r3.json().get("test_marker") == new_settings["test_marker"]
    # restore
    client.put(f"{API}/admin/settings", headers=auth_headers, json=original)
