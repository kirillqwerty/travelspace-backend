import re

import server
from tour_program_pdf import _date_rows, _stacked_date_label, build_tour_program_pdf


def _long_tour():
    marker = "Уникальный финальный абзац программы"
    return {
        "id": "tour-pdf-test",
        "slug": "test-tour",
        "title": "Большой тестовый тур из Минска",
        "tagline": "Полная программа поездки без ручного дублирования данных.",
        "description": "Подробное описание маршрута, условий и особенностей путешествия.",
        "duration": "20 дней",
        "departure_cities": ["Минск", "Гомель"],
        "region_name": "Тестовое направление",
        "price_from": 1200,
        "currency": "BYN",
        "dates": [
            {
                "start": "2099-06-01",
                "end": "2099-06-20",
                "price": 1250,
                "currency": "BYN",
            }
        ],
        "highlights": ["Главное впечатление маршрута"],
        "what_to_see": ["Главная достопримечательность"],
        "program": [
            {
                "day": str(day),
                "title": f"Насыщенный день {day}",
                "description": (
                    ("Полное описание дня с маршрутом, остановками и важными деталями. " * 12)
                    + (marker if day == 20 else "")
                ),
            }
            for day in range(1, 21)
        ],
        "included": ["Проезд", "Проживание", "Сопровождение"],
        "excluded": ["Личные расходы"],
        "important_info": ["Необходимо взять паспорт"],
        "faq": [{"question": "Что взять с собой?", "answer": "Документы и личные вещи."}],
    }, marker


def test_automatic_program_keeps_full_day_descriptions():
    tour, marker = _long_tour()
    program = server._default_tour_pdf_program(tour, {"company_short": "TRAVELSPACE"})

    assert program["source"] == "tour_program"
    assert len(program["days"]) == 20
    assert marker in program["days"][-1]["description"]
    assert len(program["days"][-1]["description"]) > 800


def test_pdf_uses_as_many_pages_as_content_requires():
    tour, _marker = _long_tour()
    program = server._default_tour_pdf_program(tour, {"company_short": "TRAVELSPACE"})

    pdf = build_tour_program_pdf(
        tour,
        settings={"company_short": "TRAVELSPACE", "site_url": "travelspace.by"},
        program_config=program,
    )

    page_count = len(re.findall(rb"/Type\s*/Page\b", pdf))
    assert pdf.startswith(b"%PDF-")
    assert page_count >= 3
    assert len(pdf) > 20_000


def test_direct_tour_dates_do_not_get_an_invented_option_name():
    tour, _marker = _long_tour()

    rows = _date_rows(tour)

    assert rows[0][1] == ""


def test_real_chain_name_is_kept_as_the_date_option():
    tour, _marker = _long_tour()
    tour["chains"] = [
        {
            "title": "Отель у моря",
            "dates": tour.pop("dates"),
        }
    ]

    rows = _date_rows(tour)

    assert rows[0][1] == "Отель у моря"


def test_accommodation_date_period_is_stacked():
    assert _stacked_date_label(
        {
            "date_start": "2099-06-01",
            "date_label": "01.06.2099 → 20.06.2099",
        }
    ) == "с 01.06.2099\nпо 20.06.2099"
