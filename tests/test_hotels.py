"""Canonical hotels and tour links use isolated JSON storage."""
import pytest
from fastapi.testclient import TestClient
import server
import seo_runtime
import storage


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    template = tmp_path / "index.html"
    template.write_text('<html><head><title>Test</title></head><body><div id="root"></div></body></html>', encoding="utf-8")
    monkeypatch.setattr(seo_runtime, "INDEX_HTML_PATH", template)
    storage.save("settings", {})
    storage.save("tours", [{
        "id": "tour-1", "slug": "georgia", "title": "Грузия", "active": True,
        "use_hotel_chains": True, "chains": [{
            "id": "chain-1", "title": "Расписание туров для отеля Smile", "active": True,
            "dates": [{"id": "date-1", "start": "2099-06-01", "end": "2099-06-10"}],
            "hotels": [{"id": "hotel-1", "name": "", "anchor_slug": "smile", "hotel_slug": "smile-8bbdce1dc467", "description": "У моря", "rooms": [{
                "id": "room-1", "title": "Стандарт", "description": "Балкон", "active": True,
                "date_prices": [{"date_id": "date-1", "price": 450, "currency": "USD"}], "unavailable_dates": [],
            }]}],
        }],
    }])
    server.app.dependency_overrides[server.get_current_admin] = lambda: {"email": "test@example.invalid"}
    yield TestClient(server.app)
    server.app.dependency_overrides.pop(server.get_current_admin, None)


def hotels(client):
    response = client.get("/api/admin/hotels")
    assert response.status_code == 200
    return response.json()


def first_hotel(client):
    return hotels(client)[0]


def test_legacy_profile_is_migrated_without_losing_data(client):
    hotel = first_hotel(client)
    assert hotel["name"] == "Smile"
    assert hotel["slug"] == "kobuleti-smile"
    assert hotel["rooms"][0]["date_prices"][0]["price"] == 450
    assert hotel["connections"][0]["tour_id"] == "tour-1"
    stored_hotel = storage.load("hotels")[0]
    stored_link = storage.load("tours")[0]["chains"][0]["hotels"][0]
    assert stored_hotel["description"] == "У моря"
    assert stored_link == {"id": "hotel-1", "hotel_id": "hotel-1", "anchor_slug": "smile"}


def test_hotel_is_edited_only_in_catalog_and_tour_is_hydrated(client):
    hotel = first_hotel(client)
    response = client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, "name": "Smile Hotel", "nearby": ["Море — 200 м"]})
    assert response.status_code == 200, response.text
    stored_link = storage.load("tours")[0]["chains"][0]["hotels"][0]
    assert "name" not in stored_link and "rooms" not in stored_link
    hydrated = client.get("/api/tours/georgia").json()["chains"][0]["hotels"][0]
    assert hydrated["name"] == "Smile Hotel"
    assert hydrated["nearby"] == ["Море — 200 м"]


def test_stale_tour_payload_cannot_overwrite_hotel(client):
    tour = client.get("/api/admin/tours").json()[0]
    hotel = first_hotel(client)
    assert client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, "meal": "Полупансион"}).status_code == 200
    tour["chains"][0]["hotels"][0]["meal"] = "Старое значение"
    assert client.put("/api/admin/tours/tour-1", json=tour).status_code == 200
    assert first_hotel(client)["meal"] == "Полупансион"


def test_unlinking_from_tour_does_not_delete_hotel(client):
    hotel = first_hotel(client)
    tour = client.get("/api/admin/tours").json()[0]
    tour["chains"][0]["hotels"] = []
    assert client.put("/api/admin/tours/tour-1", json=tour).status_code == 200
    assert first_hotel(client)["connections"] == []
    assert client.get(f'/api/hotels/{hotel["slug"]}').status_code == 200


def test_same_hotel_can_be_connected_to_multiple_tours(client):
    hotel = first_hotel(client)
    second = {
        "title": "Новый год в Грузии", "slug": "new-year-georgia", "active": True,
        "use_hotel_chains": True, "chains": [{
            "id": "chain-2", "active": True, "dates": [{"id": "date-2", "start": "2099-12-29", "end": "2100-01-03"}],
            "hotels": [{"id": hotel["id"], "hotel_id": hotel["id"]}],
        }],
    }
    created = client.post("/api/admin/tours", json=second)
    assert created.status_code == 200, created.text
    connections = first_hotel(client)["connections"]
    assert {item["tour_slug"] for item in connections} == {"georgia", "new-year-georgia"}
    assert {item["dates"][0]["id"] for item in connections} == {"date-1", "date-2"}


def test_new_hotel_does_not_require_tour_and_delete_unlinks_everywhere(client):
    response = client.post("/api/admin/hotels", json={"name": "Другой отель", "hotel_slug": "other-hotel", "rooms": []})
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["connections"] == []
    assert client.delete(f'/api/admin/hotels/{created["id"]}').status_code == 200
    assert all(item["id"] != created["id"] for item in hotels(client))


def test_main_dates_switch_replaces_chain_dates_in_hotel_connection(client):
    tour = client.get("/api/admin/tours").json()[0]
    tour["show_chain_dates"] = False
    tour["dates"] = [{"id": "main-date", "start": "2099-07-01", "end": "2099-07-05"}]
    assert client.put("/api/admin/tours/tour-1", json=tour).status_code == 200
    connection = first_hotel(client)["connections"][0]
    assert [item["id"] for item in connection["dates"]] == ["main-date"]


def test_duplicate_tour_reuses_same_hotel(client):
    hotel = first_hotel(client)
    response = client.post("/api/admin/tours/tour-1/duplicate")
    assert response.status_code == 200, response.text
    copied = response.json()
    assert copied["chains"][0]["hotels"][0]["id"] == hotel["id"]
    assert len(first_hotel(client)["connections"]) == 2


@pytest.mark.parametrize("field,value", [("hotel_slug", "Bad URL"), ("map_url", "javascript:alert(1)"), ("rooms", "bad"), ("rooms", ["bad"])])
def test_invalid_hotel_changes_are_rejected_atomically(client, field, value):
    hotel = first_hotel(client)
    before = storage.load("hotels")
    assert client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, field: value}).status_code == 422
    assert storage.load("hotels") == before


def test_hotel_visibility_is_owned_by_hotel_not_by_tour(client):
    hotel = first_hotel(client)
    tours = storage.load("tours")
    tours[0]["active"] = False
    storage.save("tours", tours)
    assert client.get(f'/api/hotels/{hotel["slug"]}').status_code == 200
    catalog = storage.load("hotels")
    catalog[0]["page_enabled"] = False
    storage.save("hotels", catalog)
    assert client.get(f'/api/hotels/{hotel["slug"]}').status_code == 404


def test_hotel_seo_redirects_and_tour_link(client):
    hotel = first_hotel(client)
    path = f'/hotels/{hotel["slug"]}'
    document = seo_runtime.render_index_html(path)
    assert '<h1>Smile</h1>' in document
    assert path in seo_runtime.build_sitemap_xml()
    tour = seo_runtime.get_seo_for_path("/tours/georgia")["record"]
    assert tour["chains"][0]["hotels"][0]["hotel_page_slug"] == hotel["slug"]
    assert seo_runtime.get_redirect_target("/hotels/smile-8bbdce1dc467") == "/hotels/kobuleti-smile"
    assert seo_runtime.get_redirect_target("/hotels/sweet-house-b25b6de019d6") == "/hotels/kobuleti-sweet-house"
    assert seo_runtime.get_redirect_target("/hotels/amirani-726d3fddff7c") == "/hotels/kobuleti-amirani"
    redirect = client.get("/hotels/smile-8bbdce1dc467", follow_redirects=False)
    assert redirect.status_code == 301
    assert redirect.headers["location"] == "/hotels/kobuleti-smile"


def test_deleting_tour_preserves_hotel(client):
    hotel = first_hotel(client)
    assert client.delete("/api/admin/tours/tour-1").status_code == 200
    remaining = first_hotel(client)
    assert remaining["id"] == hotel["id"]
    assert remaining["connections"] == []


def test_hotel_admin_requires_authentication(client):
    server.app.dependency_overrides.pop(server.get_current_admin, None)
    assert client.get("/api/admin/hotels").status_code == 401
    assert client.post("/api/admin/hotels", json={"name": "Unauthorized"}).status_code == 401
