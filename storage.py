"""Atomic JSON file storage for the tour operator site.

Each collection (tours, directions, specialists, leads, etc.) is stored as a
JSON document on disk at /app/backend/data/<name>.json. A single threading
lock guards reads/writes to prevent partial reads while writing.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(name)
        if lock is None:
            lock = threading.Lock()
            _locks[name] = lock
        return lock


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def load(name: str, default: Any = None) -> Any:
    """Load a JSON collection. Returns `default` if file missing."""
    p = _path(name)
    lock = _lock_for(name)
    with lock:
        if not p.exists():
            return [] if default is None else default
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)


def save(name: str, data: Any) -> None:
    """Atomically replace a JSON collection on disk."""
    p = _path(name)
    lock = _lock_for(name)
    with lock:
        tmp = p.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, p)


def list_items(name: str) -> list[dict]:
    data = load(name, default=[])
    return data if isinstance(data, list) else []


def get_by(name: str, key: str, value: Any) -> dict | None:
    for item in list_items(name):
        if item.get(key) == value:
            return item
    return None


def add_item(name: str, item: dict) -> dict:
    items = list_items(name)
    items.append(item)
    save(name, items)
    return item


def update_item(name: str, item_id: str, patch: dict) -> dict | None:
    items = list_items(name)
    updated: dict | None = None
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            items[i] = {**it, **patch}
            updated = items[i]
            break
    if updated is not None:
        save(name, items)
    return updated


def delete_item(name: str, item_id: str) -> bool:
    items = list_items(name)
    new_items = [it for it in items if it.get("id") != item_id]
    if len(new_items) == len(items):
        return False
    save(name, new_items)
    return True
