from homepage import (
    DEFAULT_HOME_PAGE,
    home_faq_content,
    home_page_content,
    homepage_settings_changed,
    settings_with_home_defaults,
)


def test_legacy_settings_receive_homepage_defaults_without_mutation():
    legacy = {"company_name": "TRAVELSPACE"}

    merged = settings_with_home_defaults(legacy)

    assert "home_page" not in legacy
    assert merged["home_page"]["h1"] == "Автобусные туры из Минска"
    assert merged["home_page"]["directions_sections"]
    assert merged["home_benefits"]["items"]


def test_empty_required_heading_falls_back_but_editor_content_is_kept():
    content = home_page_content(
        {
            "home_page": {
                "h1": "   ",
                "intro_text": "Новый текст",
                "directions_sections": [
                    {"title": "Новый H3", "text": "Текст подраздела"}
                ],
            }
        }
    )

    assert content["h1"] == DEFAULT_HOME_PAGE["h1"]
    assert content["intro_text"] == "Новый текст"
    assert content["directions_sections"][0]["title"] == "Новый H3"


def test_unrelated_settings_do_not_change_homepage_timestamp_decision():
    before = {"phone": "+375 29 000-00-00"}
    after = settings_with_home_defaults({"phone": "+375 29 111-11-11"})

    assert homepage_settings_changed(before, after) is False

    after["home_page"]["h1"] = "Новый H1"
    assert homepage_settings_changed(before, after) is True


def test_home_faq_projection_changes_only_for_visible_content():
    visible = {
        "question": "Вопрос",
        "answer": "Ответ",
        "order": 1,
        "active": True,
    }
    hidden = {**visible, "show_on_home": False}

    assert home_faq_content(visible) == ("Вопрос", "Ответ", 1)
    assert home_faq_content(hidden) is None
