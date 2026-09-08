from pathlib import Path

import seo_runtime


TOURS = [
    {
        "id": "tour-public-id",
        "slug": "public-tour",
        "title": "Тур в Грузию",
        "seo_title": "Автобусный тур в Грузию из Минска | TRAVELSPACE",
        "active": True,
        "hidden": False,
        "description": "Большая программа тура.",
        "region_name": "Грузия",
        "seo_h1": "Автобусный тур в Грузию из Минска",
        "price_from": 1200,
        "currency": "BYN",
        "program": [
            {"day": str(day), "title": f"Маршрут {day}", "description": f"Полное описание дня {day}."}
            for day in range(1, 7)
        ],
        "included": ["Проезд", "Проживание"],
        "excluded": ["Личные расходы"],
        "important_info": ["Возьмите паспорт"],
        "dates": [{"id": "date-1", "start": "2026-09-01", "end": "2026-09-07", "price": 1250, "currency": "BYN"}],
        "faq": [{"question": "Нужен ли паспорт?", "answer": "Да, документ нужен."}],
        "updated_at": "2026-08-05T08:30:00+00:00",
    },
    {
        "id": "tour-hidden-id",
        "slug": "hidden-tour",
        "title": "Скрытый тур",
        "active": True,
        "hidden": True,
    },
    {
        "slug": "inactive-tour",
        "title": "Выключенный тур",
        "active": False,
    },
    {
        "id": "tour-noindex-id",
        "slug": "noindex-tour",
        "title": "Закрытый от поиска тур",
        "active": True,
        "seo_noindex": True,
    },
    {
        "slug": "canonical-copy",
        "title": "Копия тура",
        "active": True,
        "seo_canonical_url": "/tours/public-tour",
    },
]

ARTICLES = [
    {
        "slug": "public-article",
        "title": "Статья о Грузии",
        "active": True,
        "content": "Полезный текст.",
        "published_at": "2026-08-01",
        "seo_lastmod": "18.08.2026",
    },
    {
        "slug": "hidden-article",
        "title": "SEO-статья без карточки в блоге",
        "active": True,
        "hidden": True,
        "content": "Индексируемый материал.",
        "published_at": "2026-08-02",
    },
    {
        "slug": "inactive-article",
        "title": "Выключенная статья",
        "active": False,
        "content": "Не публикуется.",
    },
]

FAQ = [
    {
        "id": "faq-home",
        "question": "Как забронировать автобусный тур?",
        "answer": "Оставьте заявку, и менеджер подтвердит наличие мест.",
        "order": 1,
        "active": True,
    },
    {
        "id": "faq-hidden-home",
        "question": "Скрытый вопрос",
        "answer": "Скрытый ответ",
        "show_on_home": False,
        "active": True,
    },
]

REVIEWS = [
    {
        "id": "review-1",
        "name": "Анна",
        "tour_name": "Тур в Грузию",
        "text": "Подробный отзыв о поездке и работе сопровождающего.",
        "active": True,
        "order": 1,
    }
]

PROMOTIONS = [
    {
        "id": "promo-1",
        "title": "Скидка для компании",
        "description": "Специальные условия для группы туристов.",
        "active": True,
    }
]

SETTINGS = {
    "home_page": {
        "h1": "Автобусные туры из Минска",
        "intro_title": "Автобусные туры из Минска и Беларуси",
        "intro_text": "Первый абзац.\n\nЧитайте про [туры в Грузию](/tours/gruziya).",
        "tours_title": "Популярные автобусные туры из Минска",
        "directions_title": "Куда можно поехать из Минска на автобусе",
        "directions_sections": [
            {
                "title": "Экскурсионные туры",
                "text": "Выберите [Санкт-Петербург](/tours/sankt-peterburg).",
                "link_label": "Все автобусные туры",
                "link_url": "/tours/avtobusnye-iz-minska",
            },
            {"title": "Автобусные туры на море", "text": "Отдых у моря."},
        ],
        "faq_title": "Частые вопросы об автобусных турах из Минска",
    },
    "home_content_updated_at": "2026-08-24T12:00:00+03:00",
}


def configure_storage(monkeypatch):
    def list_items(name):
        if name == "tours":
            return TOURS
        if name == "articles":
            return ARTICLES
        if name == "faq":
            return FAQ
        if name == "reviews":
            return REVIEWS
        if name == "promotions":
            return PROMOTIONS
        return []

    def get_by(name, key, value):
        return next((item for item in list_items(name) if item.get(key) == value), None)

    monkeypatch.setattr(seo_runtime, "list_items", list_items)
    monkeypatch.setattr(seo_runtime, "get_by", get_by)
    monkeypatch.setattr(
        seo_runtime,
        "load",
        lambda name, default=None: SETTINGS if name == "settings" else default,
    )


def test_rendered_page_has_one_metadata_set_and_semantic_snapshot(tmp_path, monkeypatch):
    configure_storage(monkeypatch)
    index_path = Path(tmp_path) / "index.html"
    index_path.write_text(
        '<!doctype html><html><head><title>SPA</title><meta name="description" content="old"></head>'
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(seo_runtime, "INDEX_HTML_PATH", index_path)

    html = seo_runtime.render_index_html("/tours/public-tour")

    assert html.count("<title") == 1
    assert html.count('name="description"') == 1
    assert html.count('rel="canonical"') == 1
    assert html.count("application/ld+json") == 1
    assert 'data-rh="true"' in html
    assert 'data-seo-prerender="true"' in html
    assert "<title data-rh=\"true\">Автобусный тур в Грузию из Минска | TRAVELSPACE</title>" in html
    assert "<h1>Тур в Грузию</h1>" in html
    assert "<h1>Автобусный тур в Грузию из Минска</h1>" not in html
    assert "Большая программа тура" in html
    assert "<h3>День 6 — Маршрут 6</h3>" in html
    assert "Полное описание дня 6." in html
    assert "Личные расходы" in html
    assert "Возьмите паспорт" in html
    assert "Нужен ли паспорт?" in html
    assert "2026-09-01 — 2026-09-07: 1250 BYN" in html


def test_status_and_indexability_are_consistent(monkeypatch):
    configure_storage(monkeypatch)

    assert seo_runtime.get_http_status_for_path("/tours/public-tour") == 200
    assert seo_runtime.get_http_status_for_path("/tours/hidden-tour") == 200
    assert seo_runtime.get_http_status_for_path("/tours/inactive-tour") == 404
    assert seo_runtime.get_http_status_for_path("/tours/noindex-tour") == 200
    assert seo_runtime.get_http_status_for_path("/blog/hidden-article") == 200
    assert seo_runtime.get_http_status_for_path("/blog/inactive-article") == 404
    assert seo_runtime.get_http_status_for_path("/does-not-exist") == 404
    assert seo_runtime.get_seo_for_path("/thanks")["no_index"] is True
    assert seo_runtime.get_seo_for_path("/does-not-exist")["no_index"] is True


def test_sitemap_contains_only_public_canonical_urls(monkeypatch):
    configure_storage(monkeypatch)

    sitemap = seo_runtime.build_sitemap_xml()

    assert "https://travelspace.by/tours/public-tour" in sitemap
    assert "https://travelspace.by/tours/hidden-tour" in sitemap
    assert "https://travelspace.by/tours/inactive-tour" not in sitemap
    assert "https://travelspace.by/tours/noindex-tour" not in sitemap
    assert "https://travelspace.by/tours/canonical-copy" not in sitemap
    assert "https://travelspace.by/tours/gruziya" in sitemap
    assert "https://travelspace.by/tours/arktika" in sitemap
    assert "https://travelspace.by/blog/hidden-article" in sitemap
    assert "https://travelspace.by/blog/inactive-article" not in sitemap
    assert (
        "<loc>https://travelspace.by/</loc>\n    <lastmod>2026-08-24</lastmod>"
        in sitemap
    )
    assert "<lastmod>2026-08-05</lastmod>" in sitemap
    assert "<lastmod>2026-08-18</lastmod>" in sitemap
    assert "changefreq" not in sitemap


def test_homepage_snapshot_matches_editable_semantic_structure(monkeypatch):
    configure_storage(monkeypatch)

    seo = seo_runtime.get_seo_for_path("/")
    snapshot = seo_runtime._render_snapshot("/", seo)

    assert snapshot.count("<h1>") == 1
    assert "<h1>Автобусные туры из Минска</h1>" in snapshot
    assert "<h2>Автобусные туры из Минска и Беларуси</h2>" in snapshot
    assert "<h2>Популярные автобусные туры из Минска</h2>" in snapshot
    assert "<h2>Куда можно поехать из Минска на автобусе</h2>" in snapshot
    assert "<h3>Экскурсионные туры</h3>" in snapshot
    assert "<h3>Автобусные туры на море</h3>" in snapshot
    assert "<h2>Почему едут именно с нами</h2>" in snapshot
    assert "<h2>Частые вопросы об автобусных турах из Минска</h2>" in snapshot
    assert "<h3>Как забронировать автобусный тур?</h3>" in snapshot
    assert "наличие мест" in snapshot
    assert "Скрытый вопрос" not in snapshot
    assert '<a href="/tours/gruziya" target="_blank" rel="noopener noreferrer">туры в Грузию</a>' in snapshot
    assert '<a href="/tours/sankt-peterburg" target="_blank" rel="noopener noreferrer">Санкт-Петербург</a>' in snapshot

    meta = seo_runtime._render_meta_block("/", seo)
    assert 'rel="canonical" href="https://travelspace.by/"' in meta
    assert '"@type":"FAQPage"' in meta


def test_seo_hub_texts_are_editable_in_server_html_and_sitemap(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(
        SETTINGS,
        "seo_hubs",
        {
            "sankt-peterburg": {
                "title": "Новый Title хаба | TRAVELSPACE",
                "description": "Новое описание хаба.",
                "heading": "Новый H1 Санкт-Петербурга",
                "intro": "Первый абзац.\n\n[Подробный тур](/tours/public-tour).",
                "catalog_title": "Актуальные туры в Санкт-Петербург из Минска",
                "content_title": "Полезный H2 после каталога",
                "content_body": "Основной текст со [ссылкой](/tours/gruziya).",
                "content_sections": [
                    {"title": "Первый H3", "text": "Текст первого подраздела."},
                    {"title": "Второй H3", "text": "Текст второго подраздела."},
                ],
                "how_to_title": "Как выбрать тур в Санкт-Петербург",
                "faq_title": "Частые вопросы о Санкт-Петербурге",
                "faq_items": [
                    {
                        "question": "Как забронировать поездку?",
                        "answer": "Выберите дату и оставьте [заявку](/contacts).",
                    }
                ],
                "seo_image": "/uploads/hub-preview.jpg",
                "content_updated_at": "2026-08-28T12:00:00+03:00",
            }
        },
    )

    seo = seo_runtime.get_seo_for_path("/tours/sankt-peterburg")
    snapshot = seo_runtime._render_snapshot("/tours/sankt-peterburg", seo)
    sitemap = seo_runtime.build_sitemap_xml()

    assert seo["title"] == "Новый Title хаба | TRAVELSPACE"
    assert seo["description"] == "Новое описание хаба."
    assert seo["image"] == "/uploads/hub-preview.jpg"
    assert "<h1>Новый H1 Санкт-Петербурга</h1>" in snapshot
    assert '<a href="/tours/public-tour" target="_blank" rel="noopener noreferrer">Подробный тур</a>' in snapshot
    assert "<h2>Актуальные туры в Санкт-Петербург из Минска</h2>" in snapshot
    assert "<h2>Полезный H2 после каталога</h2>" in snapshot
    assert "<h3>Первый H3</h3>" in snapshot
    assert '<a href="/tours/gruziya" target="_blank" rel="noopener noreferrer">ссылкой</a>' in snapshot
    assert "<h2>Как выбрать тур в Санкт-Петербург</h2>" in snapshot
    assert "<h2>Другие направления</h2>" in snapshot
    assert "<h2>Частые вопросы о Санкт-Петербурге</h2>" in snapshot
    assert "<h3>Как забронировать поездку?</h3>" in snapshot
    assert '<a href="/contacts" target="_blank" rel="noopener noreferrer">заявку</a>' in snapshot
    assert snapshot.index(
        "<h2>Актуальные туры в Санкт-Петербург из Минска</h2>"
    ) < snapshot.index(
        "<h2>Полезный H2 после каталога</h2>"
    )
    assert snapshot.index("<h2>Полезный H2 после каталога</h2>") < snapshot.index(
        "<h2>Как выбрать тур в Санкт-Петербург</h2>"
    )
    assert snapshot.index("<h2>Другие направления</h2>") < snapshot.index(
        "<h2>Частые вопросы о Санкт-Петербурге</h2>"
    )
    meta = seo_runtime._render_meta_block("/tours/sankt-peterburg", seo)
    assert '"@type":"FAQPage"' in meta
    assert 'property="og:image" content="https://travelspace.by/uploads/hub-preview.jpg"' in meta
    assert "Как забронировать поездку?" in meta
    assert "[заявку]" not in meta
    assert (
        "<loc>https://travelspace.by/tours/sankt-peterburg</loc>\n"
        "    <lastmod>2026-08-28</lastmod>"
        in sitemap
    )


def test_bus_hub_has_complete_editable_content_defaults(monkeypatch):
    configure_storage(monkeypatch)
    SETTINGS.pop("seo_hubs", None)

    seo = seo_runtime.get_seo_for_path("/tours/avtobusnye-iz-minska")
    snapshot = seo_runtime._render_snapshot("/tours/avtobusnye-iz-minska", seo)

    assert seo["content_title"].startswith("Автобусные туры из Беларуси")
    assert len(seo["content_sections"]) == 4
    assert len(seo["faq_items"]) == 8
    assert "<h3>Экскурсионные автобусные туры</h3>" in snapshot
    assert "<h2>Как выбрать автобусный тур из Минска</h2>" in snapshot
    assert "<h2>Частые вопросы об автобусных турах из Минска</h2>" in snapshot
    assert '"@type":"FAQPage"' in seo_runtime._render_meta_block(
        "/tours/avtobusnye-iz-minska", seo
    )


def test_manual_hub_tour_order_overrides_keywords_and_excludes_hidden(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(
        SETTINGS,
        "seo_hubs",
        {
            "sankt-peterburg": {
                "tour_ids": [
                    "tour-noindex-id",
                    "tour-hidden-id",
                    "tour-public-id",
                ],
            }
        },
    )

    tours = seo_runtime.tours_for_landing("/tours/sankt-peterburg")

    assert [tour["slug"] for tour in tours] == ["noindex-tour", "public-tour"]


def test_hidden_content_stays_out_of_public_lists(monkeypatch):
    configure_storage(monkeypatch)

    catalog = seo_runtime._render_snapshot(
        "/tours", seo_runtime.get_seo_for_path("/tours")
    )
    blog = seo_runtime._render_snapshot(
        "/blog", seo_runtime.get_seo_for_path("/blog")
    )

    assert "Скрытый тур" not in catalog
    assert "SEO-статья без карточки в блоге" not in blog


def test_legacy_direction_has_permanent_destination(monkeypatch):
    configure_storage(monkeypatch)
    assert (
        seo_runtime.get_redirect_target("/directions/saint-petersburg")
        == "/tours/sankt-peterburg"
    )


def test_static_pages_have_complete_server_content_and_internal_links(monkeypatch):
    configure_storage(monkeypatch)

    faq_seo = seo_runtime.get_seo_for_path("/faq")
    faq_snapshot = seo_runtime._render_snapshot("/faq", faq_seo)
    reviews_snapshot = seo_runtime._render_snapshot(
        "/reviews", seo_runtime.get_seo_for_path("/reviews")
    )
    promotions_snapshot = seo_runtime._render_snapshot(
        "/promotions", seo_runtime.get_seo_for_path("/promotions")
    )
    payment_snapshot = seo_runtime._render_snapshot(
        "/payment", seo_runtime.get_seo_for_path("/payment")
    )

    assert "Как забронировать автобусный тур?" in faq_snapshot
    assert "наличие мест" in faq_snapshot
    assert 'href="https://travelspace.by/agencies"' in faq_snapshot
    assert 'href="https://travelspace.by/legal"' in faq_snapshot
    assert "Подробный отзыв о поездке" in reviews_snapshot
    assert "Специальные условия для группы" in promotions_snapshot
    assert "Как оформить и оплатить тур" in payment_snapshot
    assert '"@type":"FAQPage"' in seo_runtime._render_meta_block("/faq", faq_seo)


def test_rich_text_links_open_a_new_tab_safely():
    html = seo_runtime._render_rich_inline(
        "[Грузия](/tours/gruziya) [Внешний сайт](https://example.com/tour?a=1&b=2)"
    )
    assert '<a href="/tours/gruziya" target="_blank" rel="noopener noreferrer">Грузия</a>' in html
    assert '<a href="https://example.com/tour?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">Внешний сайт</a>' in html
    unsafe = seo_runtime._render_rich_inline("[Первый](javascript:alert) [Второй](//example.com)")
    assert "<a " not in unsafe
    assert unsafe == "Первый Второй"


def test_hero_edits_and_bold_content_are_present_in_server_html(monkeypatch):
    configure_storage(monkeypatch)
    monkeypatch.setitem(SETTINGS, "home_page", {"hero_tagline": "Новый слоган", "hero_description": "Поездки **без хлопот**"})
    html = seo_runtime._render_snapshot("/", seo_runtime.get_seo_for_path("/"))
    assert "Новый слоган" in html
    assert "<strong>без хлопот</strong>" in html
    assert "Туры, в которые хочется возвращаться" not in html
    assert "<strong>Проезд</strong>" in seo_runtime._render_list(["**Проезд** и проживание"])
    assert "<strong>Текст</strong>" in seo_runtime._render_paragraphs("**Текст** статьи")


def test_canonical_and_robots_overrides_are_safe(monkeypatch):
    configure_storage(monkeypatch)

    canonical_copy = seo_runtime.get_seo_for_path("/tours/canonical-copy")
    assert canonical_copy["canonical_url"] == "https://travelspace.by/tours/public-tour"

    noindex = seo_runtime.get_seo_for_path("/tours/noindex-tour")
    meta = seo_runtime._render_meta_block("/tours/noindex-tour", noindex)
    assert 'name="robots" content="noindex, follow"' in meta

    assert (
        seo_runtime.canonical_url_for_path(
            "https://example.com/stolen", "/tours/public-tour"
        )
        == "https://travelspace.by/tours/public-tour"
    )
    assert (
        seo_runtime.canonical_url_for_path(
            "/does-not-exist", "/tours/public-tour"
        )
        == "https://travelspace.by/tours/public-tour"
    )
