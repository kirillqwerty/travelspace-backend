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


def test_invalid_block_does_not_write(isolated):
    with pytest.raises(server.HTTPException) as error:
        server._crud_create("articles", {"slug": "invalid", "content_blocks": [{"type": "script"}]})
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
