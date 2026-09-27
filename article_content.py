"""Ordered article blocks, with a non-destructive legacy gallery fallback."""
import re


ARTICLE_ANCHOR_RE = re.compile(r"[a-z][a-z0-9-]*\Z")


def remove_legacy_article_h1(articles):
    """Use the article title as the only H1, including for legacy records."""
    changed = False
    for article in articles:
        if "seo_h1" in article:
            del article["seo_h1"]
            changed = True
    return changed


def _public_image_source(value):
    source = str(value or "").strip()
    return source.startswith(("https://", "http://")) or source.startswith("/") and not source.startswith("//")


def article_blocks(article):
    if isinstance(article.get("content_blocks"), list):
        return article["content_blocks"]
    paragraphs = [text for text in re.split(r"\n\s*\n", str(article.get("content") or "").replace("\r\n", "\n")) if text.strip()]
    gallery = article.get("gallery")
    if not isinstance(gallery, list):
        gallery = article.get("images") or []
    alts = article.get("gallery_alts") or article.get("image_alts") or []
    images = [{"type": "image", "src": src, "alt": alts[i] if i < len(alts) else ""}
              for i, src in enumerate(gallery) if src and src != article.get("cover")]
    result = []
    next_image = 0
    for i, text in enumerate(paragraphs):
        result.append({"type": "text", "text": text})
        if i % 2 == 1 and next_image < len(images):
            result.append(images[next_image])
            next_image += 1
    return result + images[next_image:]


def article_menu_links(article):
    """Only expose menu links with one real, renderable block target."""
    if article.get("show_article_menu") is not True:
        return []
    blocks = article_blocks(article)
    anchors = [str(block.get("anchor") or "").strip() for block in blocks if isinstance(block, dict)]
    renderable = {str(block.get("anchor") or "").strip() for block in blocks
                  if isinstance(block, dict) and (
                      block.get("type") == "text" and str(block.get("text") or "").strip()
                      or block.get("type") == "image" and _public_image_source(block.get("src"))
                  )}
    items = article.get("article_menu_items")
    if not isinstance(items, list):
        return []
    seen = set()
    links = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        anchor = str(item.get("anchor") or "").strip()
        if title and ARTICLE_ANCHOR_RE.fullmatch(anchor) and anchors.count(anchor) == 1 and anchor in renderable and anchor not in seen:
            links.append({"title": title, "anchor": anchor})
            seen.add(anchor)
    return links


def sync_article_text(payload, existing=None):
    """Keep legacy excerpts/SEO consumers consistent with the canonical blocks."""
    article = {**(existing or {}), **payload}
    if not str(article.get("title") or "").strip():
        raise ValueError("Укажите заголовок статьи")
    if "faq_title" in payload:
        payload["faq_title"] = str(payload.get("faq_title") or "").strip()
    if "faq" in payload:
        if not isinstance(payload["faq"], list):
            raise ValueError("FAQ статьи должен быть списком вопросов")
        questions = []
        for item in payload["faq"]:
            if not isinstance(item, dict):
                raise ValueError("Некорректный вопрос FAQ статьи")
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question and not answer:
                continue
            if not question or not answer:
                raise ValueError("Заполните и вопрос, и ответ FAQ статьи")
            questions.append({**item, "question": question, "answer": answer})
        payload["faq"] = questions
    blocks = article.get("content_blocks")
    if blocks is not None and (not isinstance(blocks, list) or any(
        not isinstance(block, dict)
        or block.get("type") not in ("text", "image")
        or not isinstance(block.get("text" if block.get("type") == "text" else "src", ""), str)
        or not isinstance(block.get("alt", ""), str)
        for block in blocks
    )):
        raise ValueError("Некорректные блоки статьи")
    if "content_blocks" in payload:
        payload["content"] = "\n\n".join(block.get("text", "") for block in blocks if block["type"] == "text")

    for block in blocks or []:
        anchor = str(block.get("anchor") or "").strip()
        if anchor and not ARTICLE_ANCHOR_RE.fullmatch(anchor):
            raise ValueError("Якорь блока должен начинаться с латинской буквы и содержать только латиницу, цифры и дефис")
        if block.get("type") == "text":
            if not isinstance(block.get("map_place", ""), str):
                raise ValueError("Место на карте должно быть текстом")
            if block.get("show_map") is True and not str(block.get("map_place") or "").strip():
                raise ValueError("Для включённой карты укажите место")

    menu = article.get("article_menu_items") or []
    if not isinstance(menu, list) or any(not isinstance(item, dict) for item in menu):
        raise ValueError("Некорректные пункты меню статьи")
    if article.get("show_article_menu") is not True:
        return
    if not menu:
        raise ValueError("Добавьте хотя бы один пункт меню статьи")
    anchors = []
    for item in menu:
        if not str(item.get("title") or "").strip():
            raise ValueError("Укажите название каждого пункта меню статьи")
        anchor = str(item.get("anchor") or "").strip()
        if not anchor or not ARTICLE_ANCHOR_RE.fullmatch(anchor):
            raise ValueError("Укажите якорь латиницей для каждого пункта меню")
        if anchor in anchors:
            raise ValueError(f"Якорь #{anchor} повторяется в меню статьи")
        anchors.append(anchor)
    targets = [str(block.get("anchor") or "").strip() for block in blocks or []]
    for anchor in anchors:
        if targets.count(anchor) != 1:
            raise ValueError(f"Назначьте якорь #{anchor} одному непустому блоку статьи")
        block = (blocks or [])[targets.index(anchor)]
        if not str(block.get("text" if block.get("type") == "text" else "src") or "").strip():
            raise ValueError(f"Назначьте якорь #{anchor} одному непустому блоку статьи")
        if block.get("type") == "image" and not _public_image_source(block.get("src")):
            raise ValueError(f"Для якоря #{anchor} укажите корректный адрес фотографии")
    if any(anchor and anchor not in anchors for anchor in targets):
        raise ValueError("В статье есть якорь без пункта меню")
