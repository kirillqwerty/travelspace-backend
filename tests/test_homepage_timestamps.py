import asyncio
from copy import deepcopy

import server
from homepage import settings_with_home_defaults
from seo_runtime import stamp_changed_seo_hubs


def test_admin_settings_timestamp_changes_only_with_visible_home_content(monkeypatch):
    stored = {
        "phone": "+375 29 000-00-00",
        "home_content_updated_at": "2026-08-24T00:00:00+03:00",
    }
    writes = []

    monkeypatch.setattr(server, "load", lambda name, default=None: deepcopy(stored))
    monkeypatch.setattr(server, "save", lambda name, value: writes.append(deepcopy(value)))
    monkeypatch.setattr(server, "_now", lambda: "2026-08-24T15:30:00+03:00")

    contact_only = settings_with_home_defaults(
        {
            **stored,
            "phone": "+375 29 111-11-11",
        }
    )
    asyncio.run(server.admin_update_settings(contact_only, current={"id": "admin"}))

    assert writes[-1]["home_content_updated_at"] == stored["home_content_updated_at"]

    changed_home = deepcopy(contact_only)
    changed_home["home_page"]["h1"] = "Новый заголовок главной"
    asyncio.run(server.admin_update_settings(changed_home, current={"id": "admin"}))

    assert writes[-1]["home_content_updated_at"] == "2026-08-24T15:30:00+03:00"


def test_saving_unchanged_home_faq_does_not_touch_timestamp(monkeypatch):
    existing = {
        "id": "faq-1",
        "question": "Вопрос",
        "answer": "Ответ",
        "order": 1,
        "active": True,
        "show_on_home": True,
    }
    touched = []

    monkeypatch.setattr(
        server,
        "get_by",
        lambda name, key, item_id: deepcopy(existing),
    )
    monkeypatch.setattr(
        server,
        "update_item",
        lambda name, item_id, payload: {**existing, **payload},
    )
    monkeypatch.setattr(
        server,
        "_touch_home_content_timestamp",
        lambda value=None: touched.append(value),
    )

    server._crud_update("faq", "faq-1", deepcopy(existing))
    assert touched == []

    server._crud_update("faq", "faq-1", {**existing, "answer": "Новый ответ"})
    assert touched == [None]


def test_only_changed_seo_hub_receives_new_lastmod():
    before = {
        "seo_hubs": {
            "gruziya": {
                "title": "Старый Title",
                "description": "Описание",
                "heading": "Туры в Грузию",
                "intro": "Вводный текст",
                "content_updated_at": "2026-08-20T10:00:00+03:00",
            }
        }
    }
    after = deepcopy(before)
    after["seo_hubs"]["gruziya"]["intro"] = "Обновлённый вводный текст"

    stamped = stamp_changed_seo_hubs(
        before,
        after,
        "2026-08-28T16:00:00+03:00",
    )

    assert (
        stamped["seo_hubs"]["gruziya"]["content_updated_at"]
        == "2026-08-28T16:00:00+03:00"
    )


def test_changed_hub_faq_receives_new_lastmod():
    before = {
        "seo_hubs": {
            "gruziya": {
                "title": "Title",
                "description": "Описание",
                "heading": "Туры в Грузию",
                "intro": "Вводный текст",
                "faq_title": "Частые вопросы",
                "faq_items": [
                    {"question": "Как забронировать?", "answer": "Оставьте заявку."}
                ],
                "content_updated_at": "2026-08-20T10:00:00+03:00",
            }
        }
    }
    after = deepcopy(before)
    after["seo_hubs"]["gruziya"]["faq_items"][0]["answer"] = (
        "Выберите дату и оставьте заявку."
    )

    stamped = stamp_changed_seo_hubs(
        before,
        after,
        "2026-08-31T12:00:00+03:00",
    )

    assert (
        stamped["seo_hubs"]["gruziya"]["content_updated_at"]
        == "2026-08-31T12:00:00+03:00"
    )
