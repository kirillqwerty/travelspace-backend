"""Formatting shared in behavior with frontend/src/lib/richTextTokens.js."""
import re
from html import escape
from urllib.parse import urlsplit


def normalize(value):
    return re.sub(r"\](?:\s|\u200b|\ufeff|&nbsp;|&#(?:32|160);|&#x(?:20|a0);)*\(", "](", str(value or ""), flags=re.I)


def safe_url(value):
    if re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    try:
        url = urlsplit(value)
        return url.scheme.lower() in {"http", "https"} and bool(url.netloc)
    except ValueError:
        return False


def closing(text, start, opening, ending):
    depth, i = 0, start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == opening:
            depth += 1
        if text[i] == ending:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def read_link(text, start):
    if text[start:start + 1] != "[":
        return None
    label_end = closing(text, start, "[", "]")
    if label_end < 0 or text[label_end + 1:label_end + 2] != "(":
        return None
    end = closing(text, label_end + 1, "(", ")")
    if end < 0:
        return None
    return text[start + 1:label_end], text[label_end + 2:end].strip(), end + 1


def tokens(value, depth=0):
    text = normalize(value)
    if depth > 30:
        return [{"type": "text", "text": text}]
    result, i = [], 0
    while i < len(text):
        if text[i] == "\\" and text[i + 1:i + 2] and text[i + 1] in "\\[]()*_":
            result.append({"type": "text", "text": text[i + 1]})
            i += 2
            continue
        link = read_link(text, i)
        if link:
            label, href, i = link
            result.append({"type": "link", "href": href, "children": tokens(label, depth + 1)})
            continue
        url = re.match(r"https?://[^\s<>]+", text[i:], flags=re.I)
        if url:
            href = re.sub(r"[.,!?:;]+$", "", url[0])
            while href.endswith(")") and href.count(")") > href.count("("):
                href = href[:-1]
            result.append({"type": "link", "href": href, "children": [{"type": "text", "text": href}]})
            i += len(href)
            continue
        icon = re.match(r":(check|minus|warning|triangle):", text[i:])
        if icon:
            result.append({"type": "icon", "text": icon[0]})
            i += len(icon[0])
            continue
        marker = "**" if text.startswith("**", i) else "___" if text.startswith("___", i) else "__" if text.startswith("__", i) else "_" if text[i] == "_" else None
        end = -1
        if marker and not ("_" in marker and i and text[i - 1].isalnum()):
            j = i + len(marker)
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                nested = read_link(text, j)
                if nested:
                    j = nested[2]
                    continue
                if marker == "_" and text.startswith("__", j):
                    nested_end = text.find("__", j + 2)
                    if nested_end >= 0:
                        j = nested_end + 2
                        continue
                if text.startswith(marker, j) and j > i + len(marker):
                    end = j
                    break
                j += 1
        if end != -1:
            children = tokens(text[i + len(marker):end], depth + 1)
            result.append({"type": "underline", "children": [{"type": "italic", "children": children}]} if marker == "___" else {"type": {"**": "bold", "__": "underline", "_": "italic"}[marker], "children": children})
            i = end + len(marker)
            continue
        result.append({"type": "text", "text": text[i]})
        i += 1
    return result


def render_tokens(items, links=True, plain=False):
    result = []
    for item in items:
        kind = item["type"]
        if kind == "text":
            result.append(item["text"] if plain else escape(item["text"]))
        elif kind == "icon":
            if not plain:
                result.append({":check:": "✓", ":minus:": "−", ":warning:": "⚠", ":triangle:": "▸"}[item["text"]])
        else:
            content = render_tokens(item["children"], links and kind != "link", plain)
            if plain:
                result.append(content)
            elif kind == "link":
                result.append(f'<a href="{escape(item["href"], quote=True)}" target="_blank" rel="noopener noreferrer">{content}</a>' if links and safe_url(item["href"]) else content)
            else:
                tag = {"bold": "strong", "underline": "u", "italic": "em"}[kind]
                result.append(f"<{tag}>{content}</{tag}>")
    return "".join(result)


def render_inline(value):
    return render_tokens(tokens(value))


def plain_text(value):
    text = render_tokens(tokens(value), plain=True)
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"^[\s*_]+$", "", text)
    return re.sub(r"\s+", " ", re.sub(r"[`#>]+", " ", text)).strip()
