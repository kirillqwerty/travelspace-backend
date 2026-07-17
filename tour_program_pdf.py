"""One-page PDF tour program generator for public downloads."""

from __future__ import annotations

import io
import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = A4
MARGIN = 30
ORANGE = colors.HexColor("#C2410C")
ORANGE_DARK = colors.HexColor("#9A3412")
DARK = colors.HexColor("#111827")
MUTED = colors.HexColor("#5B6472")
LIGHT = colors.HexColor("#FFF4ED")
LINE = colors.HexColor("#E7DED6")
SOFT_ORANGE = colors.HexColor("#FFEDD5")

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

MODULE_DIR = Path(__file__).resolve().parent
FONT_DIR = MODULE_DIR / "fonts"

CYRILLIC_FONT_PAIRS = [
    # The first pair is shipped with the backend, so PDF generation does not
    # depend on fonts installed in the hosting container.
    (FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"),
    # Optional explicit paths for non-standard hosting environments.
    (
        Path(os.environ["PDF_FONT_REGULAR"]).expanduser()
        if os.environ.get("PDF_FONT_REGULAR")
        else None,
        Path(os.environ["PDF_FONT_BOLD"]).expanduser()
        if os.environ.get("PDF_FONT_BOLD")
        else None,
    ),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf")),
    (Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
    (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
    (Path("/usr/local/share/fonts/DejaVuSans.ttf"), Path("/usr/local/share/fonts/DejaVuSans-Bold.ttf")),
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
]


def _register_fonts() -> tuple[str, str]:
    errors: list[str] = []

    for regular, bold in CYRILLIC_FONT_PAIRS:
        if regular is None or not regular.is_file():
            continue

        bold = bold if bold is not None and bold.is_file() else regular
        try:
            pdfmetrics.registerFont(TTFont("TravelspaceSans", str(regular)))
            pdfmetrics.registerFont(TTFont("TravelspaceSans-Bold", str(bold)))
            return "TravelspaceSans", "TravelspaceSans-Bold"
        except Exception as exc:
            errors.append(f"{regular}: {exc}")

    details = f" Errors: {'; '.join(errors)}" if errors else ""
    raise RuntimeError(
        "A TrueType font with Cyrillic support was not found. "
        f"Upload DejaVuSans.ttf and DejaVuSans-Bold.ttf to {FONT_DIR}."
        + details
    )


FONT_REGULAR, FONT_BOLD = _register_fonts()


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _strip_rich_text(value: Any) -> str:
    text = _as_text(value)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("_", "")
    text = text.replace("\r", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.replace("•", "-")

    # Remove emoji and pictograms that are not reliably available in PDF fonts.
    cleaned = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if ord(char) > 0xFFFF or category in {"So", "Cs"}:
            continue
        cleaned.append(char)

    return "".join(cleaned).strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", _strip_rich_text(value)).strip()


def _truncate_words(value: Any, limit: int) -> str:
    text = _compact(value)
    if len(text) <= limit:
        return text

    cut = text[: max(0, limit - 1)].rsplit(" ", 1)[0].strip()
    return f"{cut}..." if cut else text[:limit].strip()


def _text_width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _wrap_text(text: Any, font: str, size: float, max_width: float, max_lines: int | None = None) -> list[str]:
    words = _compact(text).split()
    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or _text_width(candidate, font, size) <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word

        if max_lines and len(lines) >= max_lines:
            lines[-1] = lines[-1].rstrip(".,;: ") + "..."
            return lines

    if current:
        lines.append(current)

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "..."

    return lines


def _draw_wrapped(
    c: canvas.Canvas,
    text: Any,
    x: float,
    y: float,
    width: float,
    font: str,
    size: float,
    color=colors.black,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.22
    c.setFont(font, size)
    c.setFillColor(color)

    for line in _wrap_text(text, font, size, width, max_lines):
        c.drawString(x, y, line)
        y -= leading

    return y


def _fit_text(c: canvas.Canvas, text: str, x: float, y: float, width: float, font: str, size: float, min_size: float = 7) -> float:
    actual_size = size
    while actual_size > min_size and _text_width(text, font, actual_size) > width:
        actual_size -= 0.5

    c.setFont(font, actual_size)
    c.drawString(x, y, text)
    return actual_size


def _media_path(value: str, upload_dir: Path | None) -> Path | None:
    if not value or not upload_dir:
        return None

    source = value.strip()
    if source.startswith("/uploads/"):
        candidate = upload_dir / source.replace("/uploads/", "", 1)
        return candidate if candidate.exists() else None

    if source.startswith("uploads/"):
        candidate = upload_dir / source.replace("uploads/", "", 1)
        return candidate if candidate.exists() else None

    candidate = Path(source)
    if candidate.is_file():
        return candidate

    return None


def _draw_cover_image(c: canvas.Canvas, image_path: Path | None, x: float, y: float, width: float, height: float) -> None:
    c.setFillColor(colors.HexColor("#D8C2AE"))
    c.rect(x, y, width, height, stroke=0, fill=1)

    if not image_path:
        return

    try:
        image = ImageReader(str(image_path))
        image_w, image_h = image.getSize()
        scale = max(width / image_w, height / image_h)
        draw_w = image_w * scale
        draw_h = image_h * scale
        draw_x = x + (width - draw_w) / 2
        draw_y = y + (height - draw_h) / 2

        c.saveState()
        clip = c.beginPath()
        clip.rect(x, y, width, height)
        c.clipPath(clip, stroke=0, fill=0)
        c.drawImage(image, draw_x, draw_y, draw_w, draw_h, mask="auto")
        c.restoreState()
    except Exception:
        return


def _format_currency(currency: str | None) -> str:
    return currency or "BYN"


def _format_price(item: dict) -> str:
    parts = []

    price = item.get("price") if item.get("price") not in (None, "") else item.get("price_from")
    if price not in (None, ""):
        prefix = item.get("price_type") or "от"
        if prefix == "from":
            prefix = "от"
        parts.append(f"{prefix} {price} {_format_currency(item.get('currency'))}")

    if item.get("additional_price") not in (None, ""):
        parts.append(f"{item.get('additional_price')} {_format_currency(item.get('additional_currency'))}")

    return " + ".join(parts) or "Стоимость уточняйте"


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")

    raw = _as_text(value)
    if not raw:
        return ""

    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%d.%m.%Y")
    except ValueError:
        pass

    date_part = raw.split("T", 1)[0].split(" ", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_part, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue

    return raw


def _date_range(item: dict) -> str:
    start = _format_date(item.get("start") or item.get("date_start") or item.get("date"))
    end = _format_date(item.get("end"))
    if start and end:
        return f"{start} - {end}"
    return start or end


def _collect_dates(tour: dict) -> list[str]:
    raw: list[dict] = []

    if isinstance(tour.get("dates"), list):
        raw.extend([d for d in tour.get("dates") if isinstance(d, dict)])

    for chain in tour.get("chains") or []:
        if isinstance(chain, dict) and isinstance(chain.get("dates"), list):
            raw.extend([d for d in chain.get("dates") if isinstance(d, dict)])

    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = _date_range(item)
        if value and value not in seen:
            values.append(value)
            seen.add(value)

    return values


def _departure_cities(tour: dict) -> str:
    cities = tour.get("departure_cities")
    if isinstance(cities, list):
        values = [str(city).strip() for city in cities if str(city).strip()]
    else:
        values = []

    if not values and _as_text(tour.get("departure_city")):
        values = [_as_text(tour.get("departure_city"))]

    return ", ".join(values) if values else "уточняйте"


def _draw_meta_box(c: canvas.Canvas, tour: dict, x: float, y: float, width: float, height: float) -> None:
    c.setFillColor(LIGHT)
    c.roundRect(x, y - height, width, height, 11, stroke=0, fill=1)

    dates = _collect_dates(tour)
    if dates:
        date_values = dates[:5]
        if len(dates) > 5:
            date_values.append("и другие даты")
    else:
        date_values = ["уточняйте"]

    columns = [
        ("Ближайшие даты", date_values),
        ("Длительность", [_compact(tour.get("duration")) or "уточняйте"]),
        ("Выезд", [_departure_cities(tour)]),
        ("Стоимость", [_format_price(tour)]),
    ]

    column_w = width / len(columns)
    for idx, (label, values) in enumerate(columns):
        cx = x + idx * column_w + 10
        if idx:
            c.setStrokeColor(colors.HexColor("#E5D6CC"))
            c.line(x + idx * column_w, y - height + 10, x + idx * column_w, y - 10)

        c.setFillColor(ORANGE_DARK)
        c.setFont(FONT_BOLD, 7.6)
        c.drawString(cx, y - 15, label.upper())

        line_y = y - 30
        bottom = y - height + 10
        for value_idx, value in enumerate(values):
            if line_y < bottom:
                break

            if label == "Ближайшие даты":
                c.setFillColor(DARK)
                _fit_text(c, value, cx, line_y, column_w - 20, FONT_BOLD, 7.8, min_size=6.3)
                line_y -= 9.7
                if value_idx < len(values) - 1:
                    line_y -= 1.2
                continue

            lines = _wrap_text(value, FONT_BOLD, 8.4, column_w - 20, max_lines=2)
            for line in lines:
                if line_y < bottom:
                    break
                c.setFillColor(DARK)
                c.setFont(FONT_BOLD, 8.4)
                c.drawString(cx, line_y, line)
                line_y -= 9.8

def _draw_section_title(c: canvas.Canvas, text: str, x: float, y: float, width: float) -> float:
    c.setFillColor(ORANGE)
    c.roundRect(x, y - 17, width, 19, 6, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 12.2)
    c.drawString(x + 10, y - 12.4, text.upper())
    return y - 25


def _program_font_settings(days_count: int, available_height: float) -> tuple[float, float, int, int]:
    if days_count <= 0:
        return 9.2, 8.3, 2, 280

    avg_available = max(10, available_height / days_count)
    if avg_available >= 31:
        return 10.2, 8.9, 2, 230
    if avg_available >= 23:
        return 9.7, 8.3, 1, 170
    if avg_available >= 18:
        return 9.1, 7.7, 1, 125
    return 8.6, 7.2, 1, 90


def _draw_program(
    c: canvas.Canvas,
    tour: dict,
    program_config: dict,
    x: float,
    y: float,
    width: float,
    bottom_y: float,
) -> float:
    program = (
        program_config.get("days")
        if isinstance(program_config.get("days"), list)
        else []
    )
    program = [item for item in program if isinstance(item, dict)]

    if not program:
        description = (
            program_config.get("intro")
            or tour.get("description")
            or tour.get("short_description")
            or tour.get("tagline")
            or "Подробная программа уточняется у менеджера."
        )
        y = _draw_section_title(c, "Кратко о туре", x, y, width)
        return _draw_wrapped(c, _truncate_words(description, 760), x, y, width, FONT_REGULAR, 9.0, DARK, leading=11, max_lines=10) - 2

    y = _draw_section_title(c, "Программа тура", x, y, width)

    count = len(program)
    title_size, body_size, max_body_lines, max_desc = _program_font_settings(count, y - bottom_y)
    title_leading = title_size * 1.13
    body_leading = body_size * 1.16

    for index, day in enumerate(program, start=1):
        if y < bottom_y + 16:
            break

        day_number = _as_text(day.get("day")) or str(index)
        title = _compact(day.get("title")) or f"День {day_number}"
        description = _truncate_words(day.get("description") or day.get("notes") or "", max_desc)

        c.setFillColor(ORANGE)
        c.circle(x + 10, y - 5, 8.5, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 6.9)
        c.drawCentredString(x + 10, y - 7.5, day_number[:3])

        text_x = x + 27
        title_text = f"День {day_number}. {title}"
        y = _draw_wrapped(c, title_text, text_x, y, width - 27, FONT_BOLD, title_size, DARK, leading=title_leading, max_lines=1)

        if description and y > bottom_y + 12:
            y = _draw_wrapped(
                c,
                description,
                text_x,
                y + 1,
                width - 27,
                FONT_REGULAR,
                body_size,
                colors.HexColor("#3F3F46"),
                leading=body_leading,
                max_lines=max_body_lines,
            )

        y -= 3
        if index < count and y > bottom_y + 12:
            c.setStrokeColor(LINE)
            c.setLineWidth(0.55)
            c.line(text_x, y, x + width, y)
            y -= 5

    return y


def _wrap_bullet_item(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = _compact(text).split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    first_prefix = "- "
    next_prefix = "  "

    for word in words:
        prefix = first_prefix if not lines else next_prefix
        candidate_body = f"{current} {word}".strip()
        candidate = prefix + candidate_body

        if not current or _text_width(candidate, font, size) <= max_width:
            current = candidate_body
            continue

        lines.append(prefix + current)
        current = word

    if current:
        prefix = first_prefix if not lines else next_prefix
        lines.append(prefix + current)

    return lines


def _info_lines(items: list[str], width: float, size: float) -> list[str]:
    values = [_compact(item) for item in items if _compact(item)]
    if not values:
        values = ["Уточняйте у менеджера."]

    lines: list[str] = []
    for item in values:
        lines.extend(_wrap_bullet_item(item, FONT_REGULAR, size, width))
    return lines


def _measure_info_blocks(blocks: list[tuple[str, list[str]]], width: float, available_height: float) -> tuple[float, float, float, list[list[str]]]:
    gap = 8
    box_w = (width - gap * 2) / 3
    body_width = box_w - 16

    for size in (7.8, 7.4, 7.0, 6.6, 6.2, 5.8, 5.4, 5.0, 4.6, 4.2, 3.9, 3.6):
        leading = size * 1.15
        all_lines = [_info_lines(items, body_width, size) for _, items in blocks]
        height = 28 + max((len(lines) * leading for lines in all_lines), default=0) + 9
        if height <= available_height:
            return height, size, leading, all_lines

    size = 3.4
    leading = size * 1.12
    all_lines = [_info_lines(items, body_width, size) for _, items in blocks]
    height = min(available_height, 28 + max((len(lines) * leading for lines in all_lines), default=0) + 7)
    return height, size, leading, all_lines


def _draw_info_blocks(
    c: canvas.Canvas,
    blocks: list[tuple[str, list[str]]],
    x: float,
    y: float,
    width: float,
    height: float,
    body_size: float,
    leading: float,
    all_lines: list[list[str]],
) -> None:
    gap = 8
    box_w = (width - gap * 2) / 3

    for idx, ((title, _items), lines) in enumerate(zip(blocks, all_lines)):
        bx = x + idx * (box_w + gap)
        c.setFillColor(colors.white)
        c.setStrokeColor(ORANGE)
        c.setLineWidth(0.85)
        c.roundRect(bx, y - height, box_w, height, 9, stroke=1, fill=1)

        c.setFillColor(ORANGE)
        c.roundRect(bx, y - 22, box_w, 22, 9, stroke=0, fill=1)
        c.rect(bx, y - 22, box_w, 10, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 8.2)
        _fit_text(c, title.upper(), bx + 8, y - 15, box_w - 16, FONT_BOLD, 8.2, min_size=5.6)

        c.setFillColor(colors.HexColor("#2F3137"))
        c.setFont(FONT_REGULAR, body_size)
        line_y = y - 30
        bottom = y - height + 7
        for line in lines:
            if line_y < bottom:
                break
            c.drawString(bx + 8, line_y, line)
            line_y -= leading

def build_tour_program_pdf(
    tour: dict,
    settings: dict | None = None,
    upload_dir: Path | None = None,
    program_config: dict | None = None,
) -> bytes:
    """Build a compact, strictly one-page PDF program for a tour."""

    settings = settings or {}
    program_config = program_config if isinstance(program_config, dict) else {
        "intro": tour.get("tagline") or tour.get("short_description") or "",
        "days": tour.get("program") if isinstance(tour.get("program"), list) else [],
        "included": tour.get("included") or [],
        "excluded": tour.get("excluded") or [],
        "important_info": tour.get("important_info") or [],
        "show_info_blocks": True,
    }
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(_compact(tour.get("title")) or "Программа тура")
    c.setAuthor(_compact(settings.get("company_short")) or "TRAVELSPACE")

    # Background.
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    hero_h = 112
    image = _media_path(_as_text(tour.get("hero_image") or tour.get("seo_image")), upload_dir)
    _draw_cover_image(c, image, 0, PAGE_H - hero_h, PAGE_W, hero_h)

    # Dark overlay and header.
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.36))
    c.rect(0, PAGE_H - hero_h, PAGE_W, hero_h, stroke=0, fill=1)

    company = _compact(settings.get("company_short") or settings.get("company_name") or "TRAVELSPACE")
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 14)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 26, company)

    title = _compact(tour.get("title")) or "Программа тура"
    title_lines = _wrap_text(title.upper(), FONT_BOLD, 20.5, PAGE_W - MARGIN * 2, max_lines=2)
    title_box_h = 32 + max(0, len(title_lines) - 1) * 20
    title_box_y = PAGE_H - hero_h + 18
    c.setFillColor(ORANGE)
    c.roundRect(MARGIN, title_box_y, PAGE_W - MARGIN * 2, title_box_h, 7, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 20.5)
    line_y = title_box_y + title_box_h - 23
    for line in title_lines:
        c.drawString(MARGIN + 12, line_y, line)
        line_y -= 20

    y = PAGE_H - hero_h - 10
    tagline = _compact(program_config.get("intro"))
    if tagline:
        y = _draw_wrapped(c, _truncate_words(tagline, 165), MARGIN, y, PAGE_W - MARGIN * 2, FONT_BOLD, 8.9, MUTED, leading=10.2, max_lines=2)
        y -= 3

    meta_h = 73
    _draw_meta_box(c, tour, MARGIN, y, PAGE_W - MARGIN * 2, meta_h)
    y -= meta_h + 12

    footer_y = 13
    c.setStrokeColor(LINE)
    c.line(MARGIN, footer_y + 10, PAGE_W - MARGIN, footer_y + 10)
    c.setFillColor(MUTED)
    c.setFont(FONT_REGULAR, 7.2)
    contacts = _compact(settings.get("phone") or settings.get("company_phone") or "+375 29 636 99 11")
    site = _compact(settings.get("site_url") or "travelspace.by")
    c.drawString(MARGIN, footer_y, f"{company} · {site} · {contacts}")

    included = [
        _compact(item)
        for item in (program_config.get("included") or [])
        if _compact(item)
    ]
    excluded = [
        _compact(item)
        for item in (program_config.get("excluded") or [])
        if _compact(item)
    ]
    important = [
        _compact(item)
        for item in (program_config.get("important_info") or [])
        if _compact(item)
    ]
    info_blocks = [
        ("В стоимость входит", included),
        ("Оплачивается отдельно", excluded),
        ("Важно знать", important),
    ]

    program = (
        program_config.get("days")
        if isinstance(program_config.get("days"), list)
        else []
    )
    days_count = len([item for item in program if isinstance(item, dict)])
    show_info_blocks = program_config.get("show_info_blocks") is not False

    if show_info_blocks:
        min_program_height = 86 + days_count * (
            27 if days_count <= 5 else 23 if days_count <= 10 else 18
        )
        info_available = max(
            112,
            min(300, y - (footer_y + 25) - min_program_height),
        )
        info_h, info_size, info_leading, info_lines = _measure_info_blocks(
            info_blocks,
            PAGE_W - MARGIN * 2,
            info_available,
        )
        program_bottom_y = footer_y + 25 + info_h + 10
    else:
        info_h = 0
        info_size = 0
        info_leading = 0
        info_lines = []
        program_bottom_y = footer_y + 27

    y_after_program = _draw_program(
        c,
        tour,
        program_config,
        MARGIN,
        y,
        PAGE_W - MARGIN * 2,
        program_bottom_y,
    )

    if show_info_blocks:
        info_top = min(y_after_program - 9, y - 86)
        min_info_top = footer_y + 25 + info_h
        if info_top < min_info_top:
            info_top = min_info_top

        _draw_info_blocks(
            c,
            info_blocks,
            MARGIN,
            info_top,
            PAGE_W - MARGIN * 2,
            info_h,
            info_size,
            info_leading,
            info_lines,
        )

    c.showPage()
    c.save()
    return buffer.getvalue()
