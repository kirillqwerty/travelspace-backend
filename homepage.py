"""Shared homepage content defaults and SEO helpers.

The production settings file predates the editable homepage fields.  Runtime
defaults keep the public page, admin form and server-rendered HTML useful before
an editor saves the new fields for the first time.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_HOME_PAGE: dict[str, Any] = {
    "h1": "Автобусные туры из Минска",
    "intro_title": "Автобусные туры из Минска и Беларуси",
    "intro_text": (
        "TRAVELSPACE организует автобусные туры из Минска и других городов "
        "Беларуси. В программах заранее указаны маршрут, даты, проживание, "
        "экскурсии и состав стоимости.\n\n"
        "Выберите подходящее направление в каталоге "
        "[автобусных туров из Минска](/tours/avtobusnye-iz-minska) — "
        "менеджер поможет сравнить программы и оформить поездку."
    ),
    "tours_title": "Популярные автобусные туры из Минска",
    "directions_title": "Куда можно поехать из Минска на автобусе",
    "directions_sections": [
        {
            "title": "Экскурсионные туры",
            "text": (
                "Для насыщенной поездки подойдут туры в "
                "[Санкт-Петербург](/tours/sankt-peterburg), "
                "[Дагестан](/tours/dagestan), "
                "[Карелию](/tours/kareliya) и "
                "[Арктику](/tours/arktika)."
            ),
            "link_label": "Все экскурсионные туры",
            "link_url": "/tours/avtobusnye-iz-minska",
        },
        {
            "title": "Автобусные туры на море",
            "text": (
                "Автобусные туры на море сочетают организованный выезд, "
                "проживание и отдых. Посмотрите программы поездок в "
                "[Грузию](/tours/gruziya) и [Абхазию](/tours/abhaziya)."
            ),
            "link_label": "Выбрать тур на море",
            "link_url": "/tours/avtobusnye-iz-minska",
        },
    ],
    "faq_title": "Частые вопросы об автобусных турах из Минска",
}

DEFAULT_HOME_BENEFITS: dict[str, Any] = {
    "overline": "Почему едут именно с нами",
    "title": "Заботимся о каждой детали поездки",
    "items": [
        {
            "icon": "badge",
            "title": "Сами туроператоры",
            "desc": "Не посредник: формируем туры под себя и отвечаем за качество.",
        },
        {
            "icon": "bus",
            "title": "Удобное отправление",
            "desc": "Подбираем комфортный вариант дороги автобусом или самолётом.",
        },
        {
            "icon": "users",
            "title": "Поддержка менеджера",
            "desc": "С момента заявки и до возвращения — всегда на связи.",
        },
        {
            "icon": "map",
            "title": "Понятные программы",
            "desc": "Без скрытых трансферов и сюрпризов: всё показано в маршруте.",
        },
        {
            "icon": "shield",
            "title": "Проверенные маршруты",
            "desc": "Каждый тур мы прошли сами, прежде чем пустить группу.",
        },
        {
            "icon": "wallet",
            "title": "Оплата через ЕРИП",
            "desc": "Удобно и безопасно: оплата после общения с менеджером.",
        },
        {
            "icon": "seat",
            "title": "Комфорт в дороге",
            "desc": "Менеджер заранее расскажет о транспорте и доступных местах.",
        },
    ],
}

HOME_CONTENT_MIGRATION_TIMESTAMP = "2026-08-24T00:00:00+03:00"


def home_page_content(settings: Any) -> dict[str, Any]:
    """Return a defensive, shallow-normalized homepage configuration."""

    configured = settings.get("home_page") if isinstance(settings, dict) else None
    configured = configured if isinstance(configured, dict) else {}
    result = deepcopy(DEFAULT_HOME_PAGE)

    for key in (
        "h1",
        "intro_title",
        "intro_text",
        "tours_title",
        "directions_title",
        "faq_title",
    ):
        value = configured.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()

    sections = configured.get("directions_sections")
    if isinstance(sections, list):
        normalized_sections = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            normalized = {
                key: str(section.get(key) or "").strip()
                for key in ("title", "text", "link_label", "link_url")
            }
            if normalized["title"] or normalized["text"]:
                normalized_sections.append(normalized)
        if normalized_sections:
            result["directions_sections"] = normalized_sections

    return result


def settings_with_home_defaults(settings: Any) -> dict[str, Any]:
    result = dict(settings) if isinstance(settings, dict) else {}
    result["home_page"] = home_page_content(result)
    result["home_benefits"] = home_benefits_content(result)
    return result


def home_benefits_content(settings: Any) -> dict[str, Any]:
    configured = settings.get("home_benefits") if isinstance(settings, dict) else None
    if not isinstance(configured, dict):
        return deepcopy(DEFAULT_HOME_BENEFITS)
    result = deepcopy(DEFAULT_HOME_BENEFITS)
    result.update(configured)
    if not isinstance(result.get("items"), list) or not result["items"]:
        result["items"] = deepcopy(DEFAULT_HOME_BENEFITS["items"])
    return result


def homepage_settings_changed(before: Any, after: Any) -> bool:
    """Detect only fields that materially change visible homepage content."""

    before_dict = before if isinstance(before, dict) else {}
    after_dict = after if isinstance(after, dict) else {}
    return (
        home_page_content(before_dict) != home_page_content(after_dict)
        or home_benefits_content(before_dict) != home_benefits_content(after_dict)
    )


def is_home_faq(item: Any) -> bool:
    """Legacy FAQ items are visible on the homepage until explicitly hidden."""

    return bool(
        isinstance(item, dict)
        and item.get("active", True)
        and item.get("show_on_home", True)
        and str(item.get("question") or "").strip()
        and str(item.get("answer") or "").strip()
    )


def home_faq_content(item: Any) -> tuple[Any, ...] | None:
    """Comparable projection of the FAQ content that is visible at root."""

    if not is_home_faq(item):
        return None
    return (
        str(item.get("question") or "").strip(),
        str(item.get("answer") or "").strip(),
        item.get("order"),
    )
