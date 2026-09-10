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


def test_social_hub_settings_are_allowed_in_bootstrap():
    assert "links_page" in seo_runtime.PUBLIC_SETTINGS_FIELDS
