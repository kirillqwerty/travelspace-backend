"""Independent, editable EU visa pages and their initial sample content."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from storage import DATA_DIR, list_items, load, mutate_items, save

EU_COUNTRIES = {
    "AT": "Австрия", "BE": "Бельгия", "BG": "Болгария", "HR": "Хорватия",
    "CY": "Кипр", "CZ": "Чехия", "DK": "Дания", "EE": "Эстония",
    "FI": "Финляндия", "FR": "Франция", "DE": "Германия", "GR": "Греция",
    "HU": "Венгрия", "IE": "Ирландия", "IT": "Италия", "LV": "Латвия",
    "LT": "Литва", "LU": "Люксембург", "MT": "Мальта", "NL": "Нидерланды",
    "PL": "Польша", "PT": "Португалия", "RO": "Румыния", "SK": "Словакия",
    "SI": "Словения", "ES": "Испания", "SE": "Швеция",
}

VISA_PAGE_DEFAULT = {
    "eyebrow": "ВИЗОВЫЕ КОНСУЛЬТАЦИИ",
    "title": "Путешествие начинается с ясного плана",
    "subtitle": "Подскажем, с чего начать подготовку к поездке в выбранную страну ЕС и какие вопросы стоит уточнить до подачи документов.",
    "hero_button": "Выбрать страну", "hero_caption": "Индивидуальный ответ по вашему запросу",
    "hero_image": "", "hero_image_alt": "",
    "directions_kicker": "НАПРАВЛЕНИЯ", "card_link_text": "О направлении",
    "intro_title": "Выберите направление",
    "intro_text": "Расскажите, куда и зачем планируете поездку. Менеджер уточнит вашу ситуацию и объяснит, какую информацию нужно проверить для выбранного направления.",
    "steps_kicker": "ПОНЯТНЫЙ ПУТЬ", "steps_title": "Как проходит обращение",
    "steps": [
        {"title": "Вы выбираете страну", "text": "Откройте направление и оставьте контакт для связи."},
        {"title": "Мы уточняем детали", "text": "Обсуждаем цель поездки, сроки и вашу ситуацию."},
        {"title": "Сверяем актуальный порядок", "text": "Подскажем, где проверить официальные требования и какие следующие шаги возможны."},
    ],
    "faq_kicker": "ВОПРОСЫ И ОТВЕТЫ", "faq_title": "Частые вопросы",
    "faq": [
        {"question": "Можно ли узнать список документов заранее?", "answer": "Перечень зависит от страны, цели поездки и обстоятельств заявителя. Оставьте заявку — поможем определить, что нужно уточнить в официальных источниках."},
        {"question": "Вы гарантируете получение визы?", "answer": "Решение о выдаче визы принимает уполномоченный орган. Мы не обещаем результат заранее."},
    ],
    "cta_kicker": "НА СВЯЗИ", "cta_title": "Не знаете, с какой страны начать?",
    "cta_text": "Опишите планы поездки — поможем сориентироваться и выбрать следующий шаг.",
    "cta_button": "Задать вопрос о визе",
    "form_title": "Вопрос о визе", "form_description": "Расскажите о поездке. Менеджер свяжется с вами и уточнит детали.",
    "note": "Условия подачи могут меняться. Актуальные требования и решение по визе определяются уполномоченными органами.",
    "seo_title": "Визы в страны ЕС — консультация | TRAVELSPACE",
    "seo_description": "Выберите страну ЕС и оставьте заявку на консультацию по подготовке к поездке. Информация по направлению и связь с менеджером TRAVELSPACE.",
    "seo_h1": "",
    "seo_image": "", "seo_canonical_url": "", "seo_noindex": False, "seo_nofollow": False,
}

_SAMPLES = [
    ("FR", "france", "Франция", "во Францию", "Городские прогулки, музеи и поездки по регионам — расскажите о планах, чтобы мы помогли начать подготовку."),
    ("DE", "germany", "Германия", "в Германию", "Деловая или личная поездка: уточним вашу цель и подскажем, какие официальные правила проверить."),
    ("IT", "italy", "Италия", "в Италию", "От короткого отпуска до большого маршрута — начните с вопроса о подходящем порядке подготовки."),
    ("ES", "spain", "Испания", "в Испанию", "Планируете поездку в Испанию? Поможем собрать вопросы для проверки актуальных условий."),
    ("PL", "poland", "Польша", "в Польшу", "Для поездки к близким, по делам или на отдых — разберём ваш запрос индивидуально."),
]


def sample_visa(code: str, slug: str, country: str, destination: str, teaser: str, order: int) -> dict:
    return {
        "id": str(uuid4()), "country_code": code, "country": country, "slug": slug,
        "order": order, "active": True, "eyebrow": "ВИЗОВАЯ КОНСУЛЬТАЦИЯ",
        "back_label": "Все направления", "more_label": "Подробнее",
        "title": f"Виза {destination}", "subtitle": teaser, "card_text": teaser,
        "hero_image": "", "hero_image_alt": "", "card_image": "", "card_image_alt": "",
        "overview_kicker": "О НАПРАВЛЕНИИ", "overview_title": "Подготовка к поездке",
        "overview_text": f"Планируете поездку {destination}? Порядок подачи зависит от цели поездки и ваших обстоятельств. Расскажите о планах — поможем понять, какую актуальную информацию следует проверить перед обращением.",
        "sections": [
            {"title": "Что обсудим", "text": "Цель поездки, примерные даты, состав путешественников и вопросы, которые уже возникли."},
            {"title": "Что делать дальше", "text": "После уточнения деталей подскажем, где сверить действующие требования и как подготовиться к следующему шагу."},
        ],
        "section_kicker": "ПОДГОТОВКА", "faq_kicker": "ВОПРОСЫ И ОТВЕТЫ", "faq_title": "Вопросы по направлению",
        "faq": [{"question": "Когда лучше обратиться за консультацией?", "answer": "Когда определились со страной и примерными планами поездки. Актуальные условия стоит проверять до подготовки документов."}],
        "cta_kicker": "ВАШ СЛЕДУЮЩИЙ ШАГ", "cta_title": f"Планируете поездку {destination}?",
        "cta_text": "Оставьте контакт и коротко расскажите о поездке. Менеджер свяжется с вами для уточнения деталей.",
        "cta_button": "Обсудить визу", "form_title": f"Вопрос о визе: {country}",
        "form_description": VISA_PAGE_DEFAULT["form_description"], "note": VISA_PAGE_DEFAULT["note"],
        "seo_title": f"Виза {destination} — консультация | TRAVELSPACE",
        "seo_description": f"Информация для планирующих поездку {destination}: с чего начать подготовку и как задать вопрос менеджеру TRAVELSPACE.",
        "seo_h1": f"Виза {destination}", "seo_image": "", "seo_canonical_url": "",
        "seo_noindex": False, "seo_nofollow": False,
    }


def ensure_visa_seed() -> None:
    if not (DATA_DIR / "visa_page.json").exists():
        save("visa_page", {**deepcopy(VISA_PAGE_DEFAULT), "updated_at": datetime.now(timezone.utc).isoformat()})
    if not (DATA_DIR / "visas.json").exists():
        save("visas", [sample_visa(*item, index + 1) for index, item in enumerate(_SAMPLES)])
    else:
        # Add newly introduced editable labels to the original demo records,
        # while preserving every value subsequently changed in the admin.
        def fill_missing(items: list[dict]) -> None:
            defaults = {item[1]: sample_visa(*item, index + 1) for index, item in enumerate(_SAMPLES)}
            for item in items:
                sample = defaults.get(item.get("slug"))
                if sample and item.get("country_code") == sample["country_code"]:
                    for key, value in sample.items():
                        item.setdefault(key, value)
        mutate_items("visas", fill_missing)


def visa_page() -> dict:
    stored = load("visa_page", default={})
    return {**deepcopy(VISA_PAGE_DEFAULT), **(stored if isinstance(stored, dict) else {})}


def public_visas() -> list[dict]:
    return sorted((item for item in list_items("visas") if item.get("active", True)), key=lambda item: (int(item.get("order") or 9999), item.get("country", "")))


def public_visa(slug: str) -> dict | None:
    return next((item for item in public_visas() if item.get("slug") == slug), None)


def normalize_visa(payload: dict, existing: dict | None = None) -> dict:
    code = str(payload.get("country_code") or (existing or {}).get("country_code") or "").upper().strip()
    if code not in EU_COUNTRIES:
        raise ValueError("Выберите страну Европейского союза")
    slug = str(payload.get("slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("URL должен содержать латинские буквы, цифры и дефисы")
    if not str(payload.get("title") or "").strip():
        raise ValueError("Укажите заголовок страницы")
    record = dict(payload)
    record["country_code"] = code
    record["country"] = EU_COUNTRIES[code]
    record["slug"] = slug
    try:
        record["order"] = max(1, int(record.get("order") or 1))
    except (ValueError, TypeError) as error:
        raise ValueError("Порядок должен быть числом") from error
    record["sections"] = [item for item in record.get("sections", []) if isinstance(item, dict)]
    record["faq"] = [item for item in record.get("faq", []) if isinstance(item, dict)]
    return record


def save_visa(payload: dict, item_id: str | None = None) -> dict:
    def change(items: list[dict]) -> dict:
        existing = next((item for item in items if item.get("id") == item_id), None) if item_id else None
        if item_id and not existing:
            raise LookupError("Направление не найдено")
        record = normalize_visa(payload, existing)
        if any((item.get("slug") == record["slug"] or record["slug"] in (item.get("old_slugs") or [])) and item.get("id") != item_id for item in items):
            raise ValueError("Такой URL уже используется")
        if any(item.get("country_code") == record["country_code"] and item.get("id") != item_id for item in items):
            raise ValueError("Эта страна уже есть в разделе виз")
        old_slugs = list(existing.get("old_slugs") or []) if existing else []
        if existing and existing.get("slug") != record["slug"]:
            old_slugs.append(existing["slug"])
        record["old_slugs"] = [slug for slug in dict.fromkeys(old_slugs) if slug != record["slug"]]
        now = datetime.now(timezone.utc).isoformat()
        record["id"] = existing["id"] if existing else str(uuid4())
        record["created_at"] = existing.get("created_at", now) if existing else now
        record["updated_at"] = now
        if existing:
            existing.clear()
            existing.update(record)
        else:
            items.append(record)
        return record
    return mutate_items("visas", change)
