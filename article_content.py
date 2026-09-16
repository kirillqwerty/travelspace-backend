"""Ordered article blocks, with a non-destructive legacy gallery fallback."""
import re


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


def sync_article_text(payload):
    """Keep legacy excerpts/SEO consumers consistent with the canonical blocks."""
    if "content_blocks" not in payload:
        return
    blocks = payload["content_blocks"]
    if not isinstance(blocks, list) or any(
        not isinstance(block, dict)
        or block.get("type") not in ("text", "image")
        or not isinstance(block.get("text" if block.get("type") == "text" else "src", ""), str)
        or not isinstance(block.get("alt", ""), str)
        for block in blocks
    ):
        raise ValueError("Некорректные блоки статьи")
    payload["content"] = "\n\n".join(block.get("text", "") for block in blocks if block["type"] == "text")
