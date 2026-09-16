import json
import seo_runtime
from tests.test_seo_runtime import configure_storage, SETTINGS, TOURS


def test_static_page_faq_is_in_html_and_schema_alongside_reviews(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(SETTINGS, "seo_pages", {"reviews": {"path": "/reviews", "faq_title": "Об отзывах", "faq_items": [{"question": "Как оставить отзыв?", "answer": "Напишите **[нам](/contacts)**."}, {"question": "Без ответа", "answer": ""}]}})
    seo = seo_runtime.get_seo_for_path("/reviews")
    assert len(seo["page_faq_items"]) == 1
    snapshot = seo_runtime._render_snapshot("/reviews", seo)
    assert "Об отзывах" in snapshot
    assert 'href="/contacts"' in snapshot
    schemas = seo["structured_data"]["@graph"]
    assert {item["@type"] for item in schemas} == {"ItemList", "FAQPage"}
    assert schemas[-1]["mainEntity"][0]["acceptedAnswer"]["text"] == "Напишите нам."


def test_date_comments_survive_in_server_snapshot(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(TOURS[0], "dates", [{"start": "2027-12-25", "end": "2027-12-29", "comment": "Рождественская программа", "price": 500}])
    seo = seo_runtime.get_seo_for_path("/tours/public-tour")
    assert "Рождественская программа" in seo_runtime._render_snapshot("/tours/public-tour", seo)


def test_special_date_label_and_program_link_survive_in_server_snapshot(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(
        TOURS[0],
        "dates",
        [
            {
                "start": "2027-04-12",
                "end": "2027-04-16",
                "price": 650,
                "special_active": True,
                "special_label": "Фестиваль тюльпанов",
                "special_tour_slug": "spring-festival",
                "special_cta_label": "Открыть программу",
            }
        ],
    )

    seo = seo_runtime.get_seo_for_path("/tours/public-tour")
    snapshot = seo_runtime._render_snapshot("/tours/public-tour", seo)

    assert "Фестиваль тюльпанов" in snapshot
    assert "Открыть программу" in snapshot
    assert 'href="https://travelspace.by/tours/spring-festival"' in snapshot


def test_social_hub_settings_are_allowed_in_bootstrap():
    assert "links_page" in seo_runtime.PUBLIC_SETTINGS_FIELDS


def test_tour_youtube_block_is_in_snapshot_and_bootstrap(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(TOURS[0], "dates", [{"start": "2027-12-25", "end": "2027-12-29", "price": 500}])
    monkeypatch.setitem(TOURS[0], "important_info", ["Возьмите паспорт"])
    monkeypatch.setitem(TOURS[0], "youtube_url", '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>')
    monkeypatch.setitem(TOURS[0], "youtube_title", "Путешествие в кадре")
    seo = seo_runtime.get_seo_for_path("/tours/public-tour")
    snapshot = seo_runtime._render_snapshot("/tours/public-tour", seo)
    assert 'data-tour-youtube="true"' in snapshot
    assert snapshot.index("Даты и стоимость") < snapshot.index('data-tour-youtube="true"') < snapshot.index("Важная информация")
    assert "Путешествие в кадре" in snapshot
    assert 'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in snapshot
    assert "<iframe" not in snapshot
    assert {"youtube_url", "youtube_title"} <= seo_runtime.PUBLIC_RECORD_FIELDS
    monkeypatch.setitem(TOURS[0], "youtube_url", "")
    assert 'data-tour-youtube="true"' not in seo_runtime._render_snapshot("/tours/public-tour", seo)
    monkeypatch.setitem(TOURS[0], "youtube_url", "https://example.com/watch?v=dQw4w9WgXcQ")
    assert 'data-tour-youtube="true"' not in seo_runtime._render_snapshot("/tours/public-tour", seo)
