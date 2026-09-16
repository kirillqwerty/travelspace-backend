import server


def test_lead_email_rows_include_saved_attribution_fields():
    lead = {
        "form_type": "tour",
        "name": "Иван",
        "phone": "+375 29 123-45-67",
        "tour": "Карелия",
        "tour_slug": "kareliya",
        "region": "kareliya",
        "date": "10.10.2026",
        "comment": "2 человека",
        "source_page": "/tours/kareliya?utm_source=yandex",
        "page_url": "https://travelspace.by/tours/kareliya?utm_source=yandex",
        "landing_page": "/tours?utm_source=yandex",
        "referrer": "https://yandex.by/",
        "utm": {
            "utm_source": "yandex",
            "utm_medium": "cpc",
            "utm_campaign": "karelia_search",
            "utm_term": "тур в карелию",
            "utm_content": "ad_2",
            "unexpected": "must-not-be-rendered",
        },
        "click_ids": {
            "yclid": "123456789",
            "unexpected": "must-not-be-rendered",
        },
        "event_id": "lead_event_1",
        "ip": "203.0.113.10",
        "user_agent": "Mozilla/5.0 Test Browser",
        "id": "lead-1",
        "created_at": "2026-09-16T10:00:00+00:00",
    }

    rows = server._lead_email_rows(lead)
    values = dict(rows)

    assert values["Slug тура"] == "kareliya"
    assert values["Регион / направление"] == "kareliya"
    assert values["URL отправки заявки"].startswith("https://travelspace.by/")
    assert values["Первая страница визита"] == "/tours?utm_source=yandex"
    assert values["Источник перехода (referrer)"] == "https://yandex.by/"
    assert values["UTM source"] == "yandex"
    assert values["UTM campaign"] == "karelia_search"
    assert values["Яндекс Click ID (yclid)"] == "123456789"
    assert values["ID события аналитики"] == "lead_event_1"
    assert values["IP"] == "203.0.113.10"
    assert values["Устройство / браузер"] == "Mozilla/5.0 Test Browser"
    assert "must-not-be-rendered" not in values.values()


def test_lead_email_rows_keep_empty_attribution_readable():
    rows = dict(
        server._lead_email_rows(
            {
                "phone": "+375 29 123-45-67",
                "id": "lead-2",
                "created_at": "2026-09-16T10:00:00+00:00",
            }
        )
    )

    assert rows["UTM source"] == "—"
    assert rows["URL отправки заявки"] == "—"
    assert rows["Источник перехода (referrer)"] == "Прямой переход / не определён"
    assert not any("Click ID" in label for label in rows)


def test_lead_email_html_escapes_attribution_values(monkeypatch):
    monkeypatch.setattr(
        server,
        "load",
        lambda name, default=None: {"company_short": "TRAVELSPACE"},
    )
    message = server._build_lead_email(
        {
            "phone": "+375 29 123-45-67",
            "utm": {"utm_campaign": "<script>alert(1)</script>"},
            "id": "lead-3",
            "created_at": "2026-09-16T10:00:00+00:00",
        },
        "manager@example.com",
    )

    html = message.get_body(preferencelist=("html",)).get_content()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
