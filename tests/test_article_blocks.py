import asyncio
import json

import pytest
import server
import storage
import seo_runtime
from article_content import article_blocks


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.save("settings", {})
    return tmp_path


def test_article_blocks_survive_crud_reload_and_server_html(isolated):
    blocks = [
        {"id": "t1", "type": "text", "text": "Первый **[абзац](/tours)**"},
        {"id": "p1", "type": "image", "src": "/uploads/1.jpg", "alt": "Первое фото"},
        {"id": "t2", "type": "text", "text": "Второй абзац"},
        {"id": "p2", "type": "image", "src": "/uploads/2.jpg", "alt": 'Второе "фото"'},
        {"id": "t3", "type": "text", "text": "Третий абзац"},
    ]
    created = server._crud_create("articles", {"title": "Тест", "slug": "test-blocks", "active": True, "cover": "/cover.jpg", "content_blocks": blocks})
    blocks.insert(1, blocks.pop(3))
    server._crud_update("articles", created["id"], {"content_blocks": blocks})
    reloaded = asyncio.run(server.get_article("test-blocks"))
    assert reloaded["content_blocks"] == blocks
    assert reloaded["content"] == "Первый **[абзац](/tours)**\n\nВторой абзац\n\nТретий абзац"
    assert json.loads((isolated / "articles.json").read_text(encoding="utf8"))[0]["content_blocks"] == blocks
    seo = seo_runtime.get_seo_for_path("/blog/test-blocks")
    html = seo_runtime._render_snapshot("/blog/test-blocks", seo)
    assert html.index("2.jpg") < html.index("1.jpg")
    assert html.rfind("Второй абзац") > html.index("1.jpg")
    assert 'href="/tours"' in html and "<strong>" in html
    assert "Второе &quot;фото&quot;" in html
    assert seo_runtime._page_bootstrap("/blog/test-blocks", seo)["record"]["content_blocks"] == blocks
    server._crud_update("articles", created["id"], {"content_blocks": []})
    assert article_blocks(asyncio.run(server.get_article("test-blocks"))) == []


def test_legacy_alt_indexes_and_cover_are_preserved():
    article = {"content": "Один\n\nДва\n\nТри", "cover": "/cover.jpg", "gallery": ["/cover.jpg", "/1.jpg", "/2.jpg"], "gallery_alts": ["Обложка", "Один", "Два"]}
    blocks = article_blocks(article)
    assert [b["type"] for b in blocks] == ["text", "text", "image", "text", "image"]
    assert [(b["src"], b["alt"]) for b in blocks if b["type"] == "image"] == [("/1.jpg", "Один"), ("/2.jpg", "Два")]
    assert "content_blocks" not in article


def test_article_title_replaces_legacy_seo_h1_without_changing_url_or_meta_title(isolated):
    storage.save("articles", [{"id": "legacy", "slug": "legacy-guide", "title": "Название статьи",
        "seo_h1": "Старый SEO H1", "seo_title": "Заголовок для поиска",
        "seo_canonical_url": "/blog/legacy-guide", "active": True}])
    assert "seo_h1" not in asyncio.run(server.admin_list("articles", current={}))[0]
    seo = seo_runtime.get_seo_for_path("/blog/legacy-guide")
    html = seo_runtime._render_snapshot("/blog/legacy-guide", seo)
    assert seo["heading"] == "Название статьи"
    assert seo["title"] == "Заголовок для поиска"
    assert seo["canonical_url"].endswith("/blog/legacy-guide")
    assert "<h1>Название статьи</h1>" in html
    assert "Старый SEO H1" not in html
    assert "seo_h1" not in storage.list_items("articles")[0]

    updated = server._crud_update("articles", "legacy", {"title": "Новое название", "seo_h1": "Скрытая подмена"})
    assert updated["title"] == "Новое название"
    assert "seo_h1" not in updated
    assert seo_runtime.get_seo_for_path("/blog/legacy-guide")["heading"] == "Новое название"

    with pytest.raises(server.HTTPException) as error:
        server._crud_update("articles", "legacy", {"title": "  "})
    assert error.value.status_code == 422

    created = server._crud_create("articles", {"title": "Ещё статья", "slug": "new-guide",
        "seo_h1": "Не должно попасть в статью", "active": True})
    assert "seo_h1" not in created


def test_article_faq_survives_edit_and_appears_in_server_snapshot(isolated):
    created = server._crud_create("articles", {"title": "Маршрут", "slug": "route-faq", "active": True,
        "faq_title": "Вопросы о маршруте", "faq": [
            {"question": "Когда ехать?", "answer": "Весной."},
            {"question": "", "answer": ""},
        ]})
    assert created["faq"] == [{"question": "Когда ехать?", "answer": "Весной."}]
    assert asyncio.run(server.get_article("route-faq"))["faq"] == created["faq"]
    seo = seo_runtime.get_seo_for_path("/blog/route-faq")
    html = seo_runtime._render_snapshot("/blog/route-faq", seo)
    assert '<section><h2>Вопросы о маршруте</h2>' in html
    assert "Когда ехать?" in html and "Весной." in html

    with pytest.raises(server.HTTPException) as error:
        server._crud_update("articles", created["id"], {"faq": [{"question": "Без ответа", "answer": ""}]})
    assert error.value.status_code == 422
    server._crud_update("articles", created["id"], {"faq": []})
    empty = seo_runtime._render_snapshot("/blog/route-faq", seo_runtime.get_seo_for_path("/blog/route-faq"))
    assert '<h2>Вопросы о маршруте</h2>' not in empty


def test_invalid_block_does_not_write(isolated):
    with pytest.raises(server.HTTPException) as error:
        server._crud_create("articles", {"slug": "invalid", "content_blocks": [{"type": "script"}]})
    assert error.value.status_code == 422
    assert not storage.list_items("articles")


def test_article_menu_map_and_order_survive_reload_and_seo_snapshot(isolated):
    blocks = [
        {"id": "a", "type": "text", "text": "Начало", "anchor": "start", "show_map": True, "map_place": "Невский проспект, Санкт-Петербург"},
        {"id": "b", "type": "image", "src": "/uploads/blog.jpg", "alt": "Фото", "anchor": "photo"},
    ]
    menu = [{"id": "m1", "title": "Фото", "anchor": "photo"}, {"id": "m2", "title": "Начало", "anchor": "start"}]
    created = server._crud_create("articles", {"title": "Тест", "slug": "menu-test", "active": True,
        "show_article_menu": True, "article_menu_items": menu, "content_blocks": blocks})
    page = asyncio.run(server.get_article("menu-test"))
    assert page["article_menu_items"] == menu
    assert page["content_blocks"] == blocks
    html = seo_runtime._render_snapshot("/blog/menu-test", seo_runtime.get_seo_for_path("/blog/menu-test"))
    assert html.index('href="#photo"') < html.index('href="#start"')
    assert 'id="photo"' in html and 'id="start"' in html
    assert "Невский проспект, Санкт-Петербург" in html
    assert 'href="https://yandex.ru/maps/?text=' in html

    server._crud_update("articles", created["id"], {"article_menu_items": list(reversed(menu))})
    updated = asyncio.run(server.get_article("menu-test"))
    assert [item["anchor"] for item in updated["article_menu_items"]] == ["start", "photo"]

    # Removing a target requires removing its menu entry in the same save.
    with pytest.raises(server.HTTPException) as error:
        server._crud_update("articles", created["id"], {"content_blocks": blocks[:1]})
    assert error.value.status_code == 422
    server._crud_update("articles", created["id"], {"content_blocks": blocks[:1], "article_menu_items": [menu[1]]})
    assert len(asyncio.run(server.get_article("menu-test"))["article_menu_items"]) == 1
    server._crud_update("articles", created["id"], {"show_article_menu": False})
    off_html = seo_runtime._render_snapshot("/blog/menu-test", seo_runtime.get_seo_for_path("/blog/menu-test"))
    assert 'aria-label="Меню статьи"' not in off_html
    assert 'href="#start"' not in off_html


def test_manual_blog_heading_levels_render_in_server_html(isolated):
    server._crud_create("articles", {"title": "Перелёт", "slug": "flight-headings", "active": True,
        "content_blocks": [{"type": "text", "text": "### Самолёт: выберите аэропорт\nПрактический совет.\n#### Тбилиси: маршрут\nПолезная информация."}]})
    html = seo_runtime._render_snapshot("/blog/flight-headings", seo_runtime.get_seo_for_path("/blog/flight-headings"))
    assert "<h3>Самолёт: выберите аэропорт</h3>" in html
    assert "<h4>Тбилиси: маршрут</h4>" in html
    assert "<p>Практический совет.</p>" in html
    assert "### Самолёт" not in html


@pytest.mark.parametrize("menu,blocks", [
    ([{"title": "A", "anchor": ""}], [{"type": "text", "text": "A"}]),
    ([{"title": "A", "anchor": "same"}, {"title": "B", "anchor": "same"}], [{"type": "text", "text": "A", "anchor": "same"}]),
    ([{"title": "A", "anchor": "missing"}], [{"type": "text", "text": "A"}]),
    ([{"title": "A", "anchor": "same"}], [{"type": "text", "text": "A", "anchor": "same"}, {"type": "text", "text": "B", "anchor": "same"}]),
    ([{"title": "A", "anchor": "same"}], [{"type": "text", "text": "A", "anchor": "same", "show_map": True}]),
    ([{"title": "A", "anchor": "same"}], [{"type": "image", "src": "wrong-path", "anchor": "same"}]),
])
def test_invalid_article_menu_or_map_is_rejected(isolated, menu, blocks):
    with pytest.raises(server.HTTPException) as error:
        server._crud_create("articles", {"slug": "bad-menu", "show_article_menu": True,
            "article_menu_items": menu, "content_blocks": blocks})
    assert error.value.status_code == 422
    assert not storage.list_items("articles")


def test_faq_edit_hide_delete_and_empty_collection_do_not_restore_defaults(isolated):
    faq = server._crud_create("faq", {"question": "Вопрос", "answer": "Ответ", "active": True, "show_on_home": True, "order": 2})
    server._crud_update("faq", faq["id"], {"answer": "Новый **ответ**", "order": 1})
    assert seo_runtime._home_faq_items()[0]["answer"] == "Новый **ответ**"
    server._crud_update("faq", faq["id"], {"show_on_home": False})
    assert seo_runtime._home_faq_items() == []
    assert len(asyncio.run(server.get_faq())) == 1
    server._crud_delete("faq", faq["id"])
    assert asyncio.run(server.get_faq()) == []
    assert seo_runtime._home_faq_items() == []


def test_more_than_eight_articles_and_publication_filters(isolated):
    storage.save("articles", [{"id": str(i), "slug": f"article-{i}", "title": f"Article {i}", "active": True} for i in range(12)] + [
        {"slug": "draft", "active": False}, {"slug": "hidden", "active": True, "hidden": True}])
    assert len(asyncio.run(server.get_articles())) == 12
    assert len(seo_runtime._page_bootstrap("/blog", seo_runtime.get_seo_for_path("/blog"))["site"]["articles"]) == 12
    assert asyncio.run(server.get_article("hidden"))["hidden"]
    with pytest.raises(server.HTTPException):
        asyncio.run(server.get_article("draft"))
