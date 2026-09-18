"""Hotel/tour round trips use isolated storage, never the operator's data."""
import pytest
from fastapi.testclient import TestClient
import hotels
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
            "hotels": [{"id": "hotel-1", "name": "", "anchor_slug": "smile", "description": "У моря", "rooms": [{
                "id": "room-1", "title": "Стандарт", "description": "Балкон", "active": True,
                "date_prices": [{"date_id": "date-1", "price": 450, "currency": "USD"}], "unavailable_dates": [],
            }]}],
        }],
    }])
    server.app.dependency_overrides[server.get_current_admin] = lambda: {"email": "test@example.invalid"}
    yield TestClient(server.app)
    server.app.dependency_overrides.pop(server.get_current_admin, None)


def record(client):
    response = client.get("/api/admin/hotels")
    assert response.status_code == 200
    return response.json()[0]


def test_legacy_hotels_are_available_without_copying_storage(client):
    before = storage.load("tours")
    hotel = record(client)
    assert hotel["name"] == "Smile"
    assert hotel["tour_id"] == "tour-1"
    assert hotel["rooms"][0]["date_prices"][0]["price"] == 450
    assert storage.load("tours") == before
    assert not (storage.DATA_DIR / "hotels.json").exists()
    assert client.get(f'/api/hotels/{hotel["slug"]}').status_code == 200


def test_edit_hotel_updates_tour_rooms_and_public_page(client):
    hotel = record(client)
    hotel.update(name="Smile Hotel", meal="Завтраки", nearby=["Море — 200 м"], amenities=["Wi-Fi"])
    hotel["rooms"][0]["date_prices"][0]["price"] = 510
    response = client.put(f'/api/admin/hotels/{hotel["id"]}', json=hotel)
    assert response.status_code == 200, response.text
    tour = client.get("/api/tours/georgia").json()
    embedded = tour["chains"][0]["hotels"][0]
    assert embedded["name"] == "Smile Hotel"
    assert embedded["nearby"] == ["Море — 200 м"]
    assert embedded["rooms"][0]["date_prices"][0]["price"] == 510
    public = client.get(f'/api/hotels/{hotel["slug"]}').json()
    assert public["meal"] == "Завтраки"
    assert "revision" not in public


def test_edit_tour_updates_hotel_without_losing_extended_fields(client):
    hotel = record(client)
    response = client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, "nearby": ["Парк"], "rules": "Заезд с паспортом"})
    assert response.status_code == 200
    tour = client.get("/api/admin/tours").json()[0]
    tour["chains"][0]["hotels"][0]["description"] = "Новое описание из тура"
    tour["chains"][0]["hotels"][0]["rooms"][0]["title"] = "Комфорт"
    response = client.put("/api/admin/tours/tour-1", json=tour)
    assert response.status_code == 200, response.text
    updated = record(client)
    assert updated["description"] == "Новое описание из тура"
    assert updated["rooms"][0]["title"] == "Комфорт"
    assert updated["nearby"] == ["Парк"]
    assert updated["rules"] == "Заезд с паспортом"


def test_stale_tour_does_not_overwrite_hotel_edit(client):
    tour = client.get("/api/admin/tours").json()[0]
    hotel = record(client)
    assert client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, "meal": "Полупансион"}).status_code == 200
    assert client.put("/api/admin/tours/tour-1", json=tour).status_code == 409
    assert record(client)["meal"] == "Полупансион"


def test_stale_hotel_does_not_overwrite_tour_edit(client):
    hotel = record(client)
    tour = client.get("/api/admin/tours").json()[0]
    tour["chains"][0]["hotels"][0]["name"] = "Новое имя"
    assert client.put("/api/admin/tours/tour-1", json=tour).status_code == 200
    assert client.put(f'/api/admin/hotels/{hotel["id"]}', json=hotel).status_code == 409
    assert record(client)["name"] == "Новое имя"


def test_new_hotel_and_delete_preserve_other_hotels_and_dates(client):
    before = storage.load("tours")[0]["chains"][0]
    response = client.post("/api/admin/hotels", json={"tour_id": "tour-1", "chain_id": "chain-1", "name": "Другой отель", "hotel_slug": "other-hotel", "rooms": []})
    assert response.status_code == 200, response.text
    created = response.json()
    assert len(client.get("/api/admin/hotels").json()) == 2
    assert client.delete(f'/api/admin/hotels/{created["id"]}').status_code == 200
    after = storage.load("tours")[0]["chains"][0]
    assert after["dates"] == before["dates"]
    assert after["hotels"][0]["rooms"] == before["hotels"][0]["rooms"]
    assert client.get("/api/hotels/other-hotel").status_code == 404


def test_can_create_independent_chain_for_new_hotel(client):
    response = client.post("/api/admin/hotels", json={"tour_id": "tour-1", "chain_id": "new", "name": "New hotel"})
    assert response.status_code == 200, response.text
    assert len(storage.load("tours")[0]["chains"]) == 2
    assert response.json()["dates"] == []


@pytest.mark.parametrize("field,value", [("hotel_slug", "Bad URL"), ("map_url", "javascript:alert(1)"), ("rooms", "bad"), ("rooms", ["bad"])])
def test_invalid_changes_are_rejected_atomically(client, field, value):
    hotel = record(client)
    before = storage.load("tours")
    assert client.put(f'/api/admin/hotels/{hotel["id"]}', json={**hotel, field: value}).status_code == 422
    assert storage.load("tours") == before


def test_duplicate_slug_rejected_and_copy_tour_has_independent_hotels(client):
    hotel = record(client)
    response = client.post("/api/admin/hotels", json={"tour_id": "tour-1", "chain_id": "chain-1", "name": "Duplicate", "hotel_slug": hotel["slug"]})
    assert response.status_code == 409
    response = client.post("/api/admin/tours/tour-1/duplicate")
    assert response.status_code == 200
    copied = response.json()
    assert copied["chains"][0]["hotels"][0]["id"] != hotel["hotel_id"]
    copies = client.get("/api/admin/hotels").json()
    assert len({h["slug"] for h in copies}) == 2
    assert len(hotels.hotel_records(storage.load("tours"), public=True)) == 1


@pytest.mark.parametrize("target,field", [("hotel", "active"), ("hotel", "page_enabled"), ("chain", "active"), ("tour", "active")])
def test_hidden_pages_are_404_and_not_in_sitemap(client, target, field):
    hotel = record(client)
    tours = storage.load("tours")
    objects = {"tour": tours[0], "chain": tours[0]["chains"][0], "hotel": tours[0]["chains"][0]["hotels"][0]}
    objects[target][field] = False
    storage.save("tours", tours)
    path = f'/hotels/{hotel["slug"]}'
    assert client.get("/api" + path).status_code == 404
    assert seo_runtime.get_http_status_for_path(path) == 404
    assert path not in seo_runtime.build_sitemap_xml()


def test_hotel_seo_bootstrap_and_tour_link_are_available_without_js(client):
    hotel = record(client)
    path = f'/hotels/{hotel["slug"]}'
    document = seo_runtime.render_index_html(path)
    assert '<h1>Smile</h1>' in document
    assert '"@type":"Hotel"' in document or '"@type": "Hotel"' in document
    assert 'hotel-hotel-1' in document
    assert '"rooms"' in document
    assert path in seo_runtime.build_sitemap_xml()
    assert seo_runtime.get_http_status_for_path(path) == 200
    assert seo_runtime.get_http_status_for_path(path + "/missing") == 404
    tour = seo_runtime.get_seo_for_path("/tours/georgia")["record"]
    assert tour["chains"][0]["hotels"][0]["hotel_page_slug"] == hotel["slug"]
    tour_document = seo_runtime.render_index_html("/tours/georgia")
    assert f'href="{path}"' in tour_document


def test_deleting_tour_removes_its_hotels(client):
    hotel = record(client)
    assert client.delete("/api/admin/tours/tour-1").status_code == 200
    assert client.get("/api/admin/hotels").json() == []
    assert client.get(f'/api/hotels/{hotel["slug"]}').status_code == 404


def test_hotel_admin_requires_authentication(client):
    server.app.dependency_overrides.pop(server.get_current_admin, None)
    assert client.get("/api/admin/hotels").status_code == 401
    assert client.post("/api/admin/hotels", json={"name": "Unauthorized"}).status_code == 401
