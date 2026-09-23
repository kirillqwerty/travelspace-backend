"""Stable, search-friendly article slugs and their redirect history."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse


def normalize_article_slug(value: Any) -> str:
    """Replace word-joining underscores while preserving an existing slug."""

    slug = str(value or "").strip()
    slug = re.sub(r"_+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def _unique_slug(candidate: str, occupied: set[str]) -> str:
    if candidate not in occupied:
        return candidate
    index = 2
    while f"{candidate}-{index}" in occupied:
        index += 1
    return f"{candidate}-{index}"


def _migrate_canonical(canonical: Any, old_slug: str, new_slug: str) -> str | None:
    value = str(canonical or "").strip()
    if not value:
        return None
    old_path = f"/blog/{old_slug}"
    new_path = f"/blog/{new_slug}"
    if value.rstrip("/") == old_path:
        return new_path
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.path.rstrip("/") == old_path:
        return urlunparse(parsed._replace(path=new_path))
    return None


def migrate_article_slugs(articles: list[dict]) -> bool:
    """Move underscore slugs to hyphens and retain every old public address."""

    changed = False
    occupied = {
        str(article.get("slug") or "").strip()
        for article in articles
        if str(article.get("slug") or "").strip()
    }
    for article in articles:
        old_slug = str(article.get("slug") or "").strip()
        normalized = normalize_article_slug(old_slug)
        if not old_slug or normalized == old_slug:
            continue

        occupied.discard(old_slug)
        new_slug = _unique_slug(normalized, occupied)
        occupied.add(new_slug)
        legacy = [
            str(value).strip()
            for value in article.get("legacy_slugs") or []
            if str(value).strip()
        ]
        if old_slug not in legacy:
            legacy.append(old_slug)
        article["slug"] = new_slug
        article["legacy_slugs"] = [
            value for value in dict.fromkeys(legacy) if value != new_slug
        ]
        canonical = _migrate_canonical(
            article.get("seo_canonical_url"), old_slug, new_slug
        )
        if canonical:
            article["seo_canonical_url"] = canonical
        changed = True
    return changed


def article_redirect_target(path: str, articles: list[dict]) -> str | None:
    prefix = "/blog/"
    clean_path = "/" + str(path or "").split("?", 1)[0].split("#", 1)[0].strip("/")
    if not clean_path.startswith(prefix):
        return None
    requested = clean_path.removeprefix(prefix)
    if not requested or "/" in requested:
        return None

    for article in articles:
        current = str(article.get("slug") or "").strip()
        legacy = {
            str(value).strip()
            for value in article.get("legacy_slugs") or []
            if str(value).strip()
        }
        if requested in legacy and current:
            return prefix + current

    normalized = normalize_article_slug(requested)
    if normalized != requested and any(
        str(article.get("slug") or "").strip() == normalized
        for article in articles
    ):
        return prefix + normalized
    return None


def article_slug_patch(payload: dict, existing: dict | None = None) -> dict:
    """Normalize an admin payload and remember the address it replaces."""

    patch = dict(payload)
    if "slug" not in patch:
        return patch
    raw_slug = str(patch.get("slug") or "").strip()
    slug = normalize_article_slug(raw_slug)
    patch["slug"] = slug
    previous = str((existing or {}).get("slug") or "").strip()
    legacy = [
        str(value).strip()
        for value in (existing or {}).get("legacy_slugs") or []
        if str(value).strip()
    ]
    for value in (raw_slug, previous):
        if value and value != slug and value not in legacy:
            legacy.append(value)
    if legacy or "legacy_slugs" in patch or (existing or {}).get("legacy_slugs"):
        patch["legacy_slugs"] = [
            value for value in dict.fromkeys(legacy) if value != slug
        ]
    return patch
