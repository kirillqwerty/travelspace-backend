from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
import storage


@pytest.fixture()
def isolated_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.save("hotels", [])
    tours = [
        {"id": "bus-1", "title": "Автобус 1", "transport_type": "bus", "order": 9, "active": True},
        {"id": "air-1", "title": "Авиа 1", "transport_type": "air", "order": 4, "active": True},
        {"id": "bus-2", "title": "Автобус 2", "transport_type": "bus", "order": 2, "active": True},
        {"id": "air-2", "title": "Авиа 2", "transport_type": "air", "order": 8, "active": True},
    ]
    storage.save("tours", deepcopy(tours))
    return tours


def test_reorders_bus_and_air_sections_independently(isolated_catalog):
    result = server._reorder_tours(
        server.TourOrderIn(
            bus=["bus-1", "bus-2"],
            air=["air-2", "air-1"],
        )
    )

    stored = {tour["id"]: tour for tour in storage.list_items("tours")}
    assert stored["bus-1"]["order"] == 1
    assert stored["bus-2"]["order"] == 2
    assert stored["air-2"]["order"] == 1
    assert stored["air-1"]["order"] == 2
    assert [tour["id"] for tour in result] == ["bus-1", "bus-2", "air-2", "air-1"]


def test_reorder_rejects_stale_list_without_partial_write(isolated_catalog):
    before = storage.list_items("tours")

    with pytest.raises(HTTPException) as error:
        server._reorder_tours(
            server.TourOrderIn(bus=["bus-1"], air=["air-1", "air-2"])
        )

    assert error.value.status_code == 409
    assert storage.list_items("tours") == before


def test_new_and_moved_tours_are_appended_to_their_section(isolated_catalog):
    created = server._crud_create(
        "tours",
        {"title": "Новый автобусный", "slug": "new-bus", "transport_type": "bus"},
    )
    assert created["order"] == 10

    moved = server._crud_update(
        "tours",
        "bus-2",
        {"transport_type": "air"},
    )
    assert moved["order"] == 9


def test_admin_order_endpoint_is_not_shadowed_by_generic_tour_update(isolated_catalog):
    server.app.dependency_overrides[server.get_current_admin] = lambda: {
        "email": "test@example.invalid"
    }
    try:
        response = TestClient(server.app).put(
            "/api/admin/tours/order",
            json={
                "bus": ["bus-2", "bus-1"],
                "air": ["air-1", "air-2"],
            },
        )
    finally:
        server.app.dependency_overrides.pop(server.get_current_admin, None)

    assert response.status_code == 200
    stored = {tour["id"]: tour for tour in storage.list_items("tours")}
    assert stored["bus-2"]["order"] == 1
    assert stored["bus-1"]["order"] == 2
