"""Automatic multi-page PDF tour program generator for public downloads."""

from __future__ import annotations

import io
import os
import re
import unicodedata
from datetime import date, datetime
from html import escape as xml_escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


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
    # ``:triangle:`` is a chat/emoji alias, not a drawable PDF glyph. It used
    # to leak into descriptions as plain text, so remove it and its common
    # variants before laying out the document.
    text = re.sub(
        r"(?i):(?:small_red_)?triangle(?:_down)?:",
        " ",
        text,
    )
    text = re.sub(r"(?i):(?:check|warning|minus):", "- ", text)
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


def _limit_words(value: Any, limit: int) -> str:
    """Limit text without adding an ellipsis that cannot be rendered fully."""
    text = _compact(value)
    if len(text) <= limit:
        return text

    cut = text[:limit].rsplit(" ", 1)[0].strip().rstrip(" ,;:-")
    return cut or text[:limit].strip()


def _text_width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _wrap_text(
    text: Any,
    font: str,
    size: float,
    max_width: float,
    max_lines: int | None = None,
    append_ellipsis: bool = True,
) -> list[str]:
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
            if append_ellipsis:
                lines[-1] = lines[-1].rstrip(".,;: ") + "..."
            return lines

    if current:
        lines.append(current)

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        if append_ellipsis:
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
    append_ellipsis: bool = True,
) -> float:
    leading = leading or size * 1.22
    c.setFont(font, size)
    c.setFillColor(color)

    for line in _wrap_text(
        text,
        font,
        size,
        width,
        max_lines,
        append_ellipsis,
    ):
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


def _parse_pdf_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = _as_text(value)
    if not raw:
        return None

    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    date_part = raw.split("T", 1)[0].split(" ", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue

    return None


def _date_range(item: dict) -> str:
    start = _format_date(item.get("start") or item.get("date_start") or item.get("date"))
    end = _format_date(item.get("end"))
    if start and end:
        return f"{start} - {end}"
    return start or end


def _tour_date_sources(tour: dict) -> list[tuple[str, dict]]:
    main = [("", item) for item in tour.get("dates") or [] if isinstance(item, dict)]
    chains = [
        (_pdf_plain(chain.get("title")), item)
        for chain in tour.get("chains") or []
        if isinstance(chain, dict) and chain.get("active") is not False
        for item in chain.get("dates") or []
        if isinstance(item, dict)
    ]
    if tour.get("show_chain_dates") is False:
        return main or chains
    return (chains or main) if tour.get("use_hotel_chains") else (main or chains)


def _collect_dates(tour: dict) -> list[str]:
    raw = [item for _, item in _tour_date_sources(tour)]

    today = date.today()
    actual_dates: list[tuple[date, str]] = []

    for item in raw:
        start = _parse_pdf_date(
            item.get("start") or item.get("date_start") or item.get("date")
        )
        end = _parse_pdf_date(item.get("end"))

        # A departure that has already started is no longer a "nearest date".
        # Records without a valid date cannot be proven actual and are skipped.
        sort_date = start or end
        if sort_date is None or (start or end) < today:
            continue

        value = _date_range(item)
        if value:
            actual_dates.append((sort_date, value))

    actual_dates.sort(key=lambda item: item[0])

    values: list[str] = []
    seen: set[str] = set()
    for _sort_date, value in actual_dates:
        if value not in seen:
            values.append(value)
            seen.add(value)

    return values


DEPARTURE_CITY_GENITIVE = {
    "минск": "Минска",
    "гомель": "Гомеля",
    "жлобин": "Жлобина",
    "бобруйск": "Бобруйска",
    "москва": "Москвы",
    "витебск": "Витебска",
    "могилев": "Могилева",
    "могилёв": "Могилёва",
    "новополоцк": "Новополоцка",
    "брест": "Бреста",
    "гродно": "Гродно",
    "барановичи": "Барановичей",
    "орша": "Орши",
    "жодино": "Жодино",
    "полоцк": "Полоцка",
}


def _departure_city_genitive(value: Any) -> str:
    city = _compact(value)
    if not city:
        return ""

    return DEPARTURE_CITY_GENITIVE.get(city.casefold(), city)


def _departure_cities(tour: dict) -> str:
    cities = tour.get("departure_cities")
    if isinstance(cities, list):
        values = [str(city).strip() for city in cities if str(city).strip()]
    else:
        values = []

    if not values and _as_text(tour.get("departure_city")):
        values = [_as_text(tour.get("departure_city"))]

    values = [_departure_city_genitive(city) for city in values]
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
    # The pill ends at y - 17. Keep a visible 14 pt gap before the first day.
    return y - 31


def description_limit_for_days(days_count: int) -> int:
    """Keep each day description readable in two or three compact lines."""
    if days_count <= 3:
        return 300
    if days_count <= 5:
        return 260
    if days_count <= 7:
        return 220
    if days_count <= 10:
        return 180
    if days_count <= 14:
        return 120
    return 80


def _measure_program_height(
    descriptions: list[str],
    width: float,
    title_size: float,
    body_size: float,
    gap_before_line: float,
    gap_after_line: float,
) -> float:
    title_leading = title_size * 1.12
    body_leading = body_size * 1.16
    height = len(descriptions) * (title_leading + 2)

    for description in descriptions:
        height += len(
            _wrap_text(
                description,
                FONT_REGULAR,
                body_size,
                width,
                max_lines=3,
                append_ellipsis=False,
            )
        ) * body_leading

    if len(descriptions) > 1:
        height += (len(descriptions) - 1) * (gap_before_line + gap_after_line)

    return height


def _program_layout(
    descriptions: list[str],
    width: float,
    available_height: float,
) -> tuple[float, float, float, float]:
    """Choose the largest style that keeps every prepared line on the page."""
    styles = (
        (10.0, 8.7, 4.0, 9.0),
        (9.5, 8.2, 3.5, 8.5),
        (9.0, 7.7, 3.0, 8.0),
        (8.5, 7.2, 2.8, 7.5),
        (8.0, 6.7, 2.5, 7.0),
        (7.5, 6.2, 2.2, 6.5),
        (7.0, 5.7, 2.0, 6.0),
    )

    for style in styles:
        if _measure_program_height(descriptions, width, *style) <= available_height:
            return style

    # Extremely long programs remain one page: scale the most compact style
    # proportionally instead of silently dropping the final days.
    title_size, body_size, before, after = styles[-1]
    required = _measure_program_height(
        descriptions,
        width,
        title_size,
        body_size,
        before,
        after,
    )
    scale = min(1.0, available_height / max(required, 1))
    return (
        title_size * scale,
        body_size * scale,
        before * scale,
        after * scale,
    )


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
    description_limit = description_limit_for_days(count)
    descriptions = [
        _limit_words(
            day.get("description") or day.get("notes") or "",
            description_limit,
        )
        for day in program
    ]
    text_width = width - 27
    title_size, body_size, gap_before_line, gap_after_line = _program_layout(
        descriptions,
        text_width,
        y - bottom_y,
    )
    title_leading = title_size * 1.13
    body_leading = body_size * 1.16

    for index, day in enumerate(program, start=1):
        day_number = _as_text(day.get("day")) or str(index)
        title = _compact(day.get("title")) or f"День {day_number}"
        description = descriptions[index - 1]

        c.setFillColor(ORANGE)
        c.circle(x + 10, y - 5, 8.5, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 6.9)
        c.drawCentredString(x + 10, y - 7.5, day_number[:3])

        text_x = x + 27
        title_text = f"День {day_number}. {title}"
        c.setFillColor(DARK)
        fitted_title_size = _fit_text(
            c,
            title_text,
            text_x,
            y,
            text_width,
            FONT_BOLD,
            title_size,
            min_size=max(4.8, title_size * 0.72),
        )
        y -= max(title_leading, fitted_title_size * 1.13)

        if description:
            y = _draw_wrapped(
                c,
                description,
                text_x,
                y + 1,
                text_width,
                FONT_REGULAR,
                body_size,
                colors.HexColor("#3F3F46"),
                leading=body_leading,
                max_lines=3,
                append_ellipsis=False,
            )

        y -= 2
        if index < count:
            y -= gap_before_line
            c.setStrokeColor(LINE)
            c.setLineWidth(0.55)
            c.line(text_x, y, x + width, y)
            # Keep the next title's ascenders below the decorative line.
            y -= gap_after_line

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

def _build_one_page_legacy(
    tour: dict,
    settings: dict | None = None,
    upload_dir: Path | None = None,
    program_config: dict | None = None,
) -> bytes:
    """Legacy one-page layout kept only for backwards-compatible internals."""

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

    default_company = _compact(
        settings.get("company_short")
        or settings.get("company_name")
        or "TRAVELSPACE"
    )
    header_company = (
        _compact(program_config.get("header_company"))
        if "header_company" in program_config
        else default_company
    )
    if header_company:
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 14)
        c.drawCentredString(PAGE_W / 2, PAGE_H - 26, header_company)

    title = (
        _compact(program_config.get("header_title"))
        if "header_title" in program_config
        else _compact(tour.get("title")) or "Программа тура"
    )
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
    default_phone = _compact(
        settings.get("phone")
        or settings.get("company_phone")
        or "+375 29 636 99 11"
    )
    default_site = _compact(settings.get("site_url") or "travelspace.by")
    footer_company = (
        _compact(program_config.get("footer_company"))
        if "footer_company" in program_config
        else default_company
    )
    footer_site = (
        _compact(program_config.get("footer_site"))
        if "footer_site" in program_config
        else default_site
    )
    footer_phone = (
        _compact(program_config.get("footer_phone"))
        if "footer_phone" in program_config
        else default_phone
    )
    footer_text = " · ".join(
        value for value in (footer_company, footer_site, footer_phone) if value
    )
    if footer_text:
        _fit_text(
            c,
            footer_text,
            MARGIN,
            footer_y,
            PAGE_W - MARGIN * 2,
            FONT_REGULAR,
            7.2,
            min_size=5.8,
        )

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


MEAL_LABELS = {
    "breakfast": "завтрак",
    "breakfast_lunch": "завтрак и обед",
    "breakfast_dinner": "завтрак и ужин",
    "breakfast_full": "трёхразовое питание",
}


def _pdf_plain(value: Any) -> str:
    return (
        _strip_rich_text(value)
        .replace("—", "-")
        .replace("–", "-")
        .replace("→", "-")
        .strip()
    )


def _pdf_markup(value: Any) -> str:
    return xml_escape(_pdf_plain(value), quote=False).replace("\n", "<br/>")


def _pdf_styles() -> dict[str, ParagraphStyle]:
    return {
        "body": ParagraphStyle(
            "TravelBody",
            fontName=FONT_REGULAR,
            fontSize=9.2,
            leading=12.4,
            textColor=DARK,
            spaceAfter=3.5,
            allowWidows=0,
            allowOrphans=0,
        ),
        "intro": ParagraphStyle(
            "TravelIntro",
            fontName=FONT_BOLD,
            fontSize=10,
            leading=13.5,
            textColor=colors.HexColor("#374151"),
            spaceAfter=5,
        ),
        "section": ParagraphStyle(
            "TravelSection",
            fontName=FONT_BOLD,
            fontSize=14,
            leading=17,
            textColor=ORANGE_DARK,
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "subsection": ParagraphStyle(
            "TravelSubsection",
            fontName=FONT_BOLD,
            fontSize=10.8,
            leading=13.5,
            textColor=DARK,
            spaceBefore=4,
            spaceAfter=2,
            keepWithNext=True,
        ),
        "minor": ParagraphStyle(
            "TravelMinor",
            fontName=FONT_BOLD,
            fontSize=9.2,
            leading=12,
            textColor=colors.HexColor("#374151"),
            spaceBefore=2,
            spaceAfter=1,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "TravelBullet",
            fontName=FONT_REGULAR,
            fontSize=9,
            leading=12,
            textColor=DARK,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "TravelSmall",
            fontName=FONT_REGULAR,
            fontSize=7.7,
            leading=10.2,
            textColor=colors.HexColor("#4B5563"),
        ),
        "small_bold": ParagraphStyle(
            "TravelSmallBold",
            fontName=FONT_BOLD,
            fontSize=7.7,
            leading=10.2,
            textColor=DARK,
        ),
    }


def _rich_flowables(value: Any, style: ParagraphStyle) -> list[Paragraph]:
    text = _pdf_plain(value)
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    return [Paragraph(xml_escape(part, quote=False), style) for part in paragraphs]


def _append_rich(story: list, value: Any, style: ParagraphStyle) -> None:
    story.extend(_rich_flowables(value, style))


def _append_bullets(story: list, values: Any, style: ParagraphStyle) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        text = _pdf_plain(value)
        if text:
            story.append(Paragraph(f"- {xml_escape(text, quote=False)}", style))


def _effective_price(record: dict, fallback: dict | None = None) -> str:
    fallback = fallback or {}
    promotion = bool(record.get("promotion_active"))
    price = record.get("promotion_price") if promotion else record.get("price")
    currency = record.get("promotion_currency") if promotion else record.get("currency")
    additional = (
        record.get("promotion_additional_price")
        if promotion and record.get("promotion_additional_price") not in (None, "")
        else record.get("additional_price")
    )
    additional_currency = (
        record.get("promotion_additional_currency")
        if promotion and record.get("promotion_additional_price") not in (None, "")
        else record.get("additional_currency")
    )
    if price in (None, ""):
        price = record.get("price_from")
        if price in (None, ""):
            price = fallback.get("price_from")
        currency = currency or fallback.get("currency")
    if additional in (None, ""):
        additional = fallback.get("additional_price")
        additional_currency = additional_currency or fallback.get("additional_currency")

    parts: list[str] = []
    if price not in (None, ""):
        prefix = "от " if record.get("price_type", fallback.get("price_type")) == "from" else ""
        parts.append(f"{prefix}{price} {_format_currency(currency or fallback.get('currency'))}")
    if additional not in (None, ""):
        parts.append(
            f"{additional} {_format_currency(additional_currency or fallback.get('additional_currency'))}"
        )
    return " + ".join(parts) or "уточняйте у менеджера"


def _date_rows(tour: dict) -> list[list[str]]:
    dated: list[tuple[date, list[str]]] = []
    sources = _tour_date_sources(tour)

    today = date.today()
    for option, item in sources:
        if str(item.get("status") or "").lower() in {"hidden", "inactive", "cancelled"}:
            continue
        start = _parse_pdf_date(item.get("start") or item.get("date_start") or item.get("date"))
        end = _parse_pdf_date(item.get("end"))
        if not (start or end) or (start or end) < today:
            continue
        dated.append(
            (
                start or end,
                [
                    _date_range(item),
                    option or _pdf_plain(item.get("comment")),
                    _effective_price(item, tour),
                ],
            )
        )
    dated.sort(key=lambda item: item[0])
    return [row for _sort_date, row in dated]


def _styled_table(
    rows: list[list[Any]],
    widths: list[float],
    styles: dict[str, ParagraphStyle],
    header: bool = True,
) -> Table:
    converted: list[list[Paragraph]] = []
    for row_index, row in enumerate(rows):
        style = styles["small_bold"] if header and row_index == 0 else styles["small"]
        converted.append([Paragraph(_pdf_markup(cell), style) for cell in row])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#FAFAF9")]),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SOFT_ORANGE),
                ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE_DARK),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def _room_price_text(item: dict) -> str:
    prices = [_effective_price(item)]
    meal_prices = item.get("meal_prices") if isinstance(item.get("meal_prices"), dict) else {}
    for key, label in MEAL_LABELS.items():
        price = meal_prices.get(key)
        if not isinstance(price, dict):
            continue
        selected = price.get("promotion_price") or price.get("price")
        if selected in (None, ""):
            continue
        currency = (
            price.get("promotion_currency")
            if price.get("promotion_price") not in (None, "")
            else price.get("currency")
        )
        prices.append(f"{label}: {selected} {_format_currency(currency)}")
    return "; ".join(dict.fromkeys(prices))


def _stacked_date_label(item: dict) -> str:
    """Format an accommodation period on two explicit, easy-to-read lines."""

    label = _pdf_plain(item.get("date_label"))
    dates = re.findall(r"\b\d{2}\.\d{2}\.\d{4}\b", label)
    if len(dates) >= 2:
        return f"с {dates[0]}\nпо {dates[1]}"
    if label:
        return label
    return _format_date(item.get("date_start"))


def _append_accommodation(
    story: list,
    tour: dict,
    styles: dict[str, ParagraphStyle],
    content_width: float,
) -> None:
    groups: list[tuple[str, str, list[dict]]] = []
    direct_hotels = [
        item for item in tour.get("hotels") or [] if isinstance(item, dict) and item.get("active") is not False
    ]
    if direct_hotels:
        groups.append(("", "", direct_hotels))
    for chain in tour.get("chains") or []:
        if not isinstance(chain, dict) or chain.get("active") is False:
            continue
        hotels = [
            item for item in chain.get("hotels") or [] if isinstance(item, dict) and item.get("active") is not False
        ]
        if hotels:
            groups.append(
                (
                    _pdf_plain(chain.get("title")),
                    _pdf_plain(chain.get("description")),
                    hotels,
                )
            )
    if not groups:
        return

    story.append(Paragraph("Варианты размещения", styles["section"]))
    for group_title, group_description, hotels in groups:
        if group_title:
            story.append(Paragraph(xml_escape(group_title), styles["subsection"]))
        _append_rich(story, group_description, styles["body"])
        for hotel_index, hotel in enumerate(hotels, start=1):
            hotel_name = _pdf_plain(hotel.get("name")) or _pdf_plain(hotel.get("anchor_slug"))
            hotel_name = hotel_name or f"Вариант размещения {hotel_index}"
            story.append(Paragraph(xml_escape(hotel_name), styles["subsection"]))
            details = [
                value
                for value in (
                    f"Расположение: {_pdf_plain(hotel.get('location'))}" if _pdf_plain(hotel.get("location")) else "",
                    f"Питание: {_pdf_plain(hotel.get('meal'))}" if _pdf_plain(hotel.get("meal")) else "",
                )
                if value
            ]
            if details:
                story.append(Paragraph(xml_escape("; ".join(details)), styles["body"]))
            _append_rich(story, hotel.get("description"), styles["body"])

            for room_index, room in enumerate(hotel.get("rooms") or [], start=1):
                if not isinstance(room, dict) or room.get("active") is False:
                    continue
                room_title = _pdf_plain(room.get("title")) or f"Номер {room_index}"
                story.append(Paragraph(xml_escape(room_title), styles["minor"]))
                _append_rich(story, room.get("description"), styles["body"])
                price_rows = []
                for price in room.get("date_prices") or []:
                    if not isinstance(price, dict):
                        continue
                    date_label = _stacked_date_label(price)
                    if date_label:
                        price_rows.append([date_label, _room_price_text(price)])
                if price_rows:
                    story.append(
                        _styled_table(
                            [["Дата", "Стоимость"]] + price_rows,
                            [content_width * 0.34, content_width * 0.66],
                            styles,
                        )
                    )
                    story.append(Spacer(1, 3))


def build_tour_program_pdf(
    tour: dict,
    settings: dict | None = None,
    upload_dir: Path | None = None,
    program_config: dict | None = None,
) -> bytes:
    """Build a compact multi-page PDF from every relevant tour text field."""

    settings = settings or {}
    program_config = program_config if isinstance(program_config, dict) else {}
    styles = _pdf_styles()
    buffer = io.BytesIO()
    content_width = PAGE_W - MARGIN * 2
    first_top = 168
    footer_height = 28

    default_company = _pdf_plain(
        settings.get("company_short") or settings.get("company_name") or "TRAVELSPACE"
    )
    title = _pdf_plain(program_config.get("header_title") or tour.get("title")) or "Программа тура"
    footer_values = [
        _pdf_plain(program_config.get("footer_company") or default_company),
        _pdf_plain(program_config.get("footer_site") or settings.get("site_url") or "travelspace.by"),
        _pdf_plain(
            program_config.get("footer_phone")
            or settings.get("phone")
            or settings.get("company_phone")
            or "+375 29 636 99 11"
        ),
    ]
    footer_text = " | ".join(value for value in footer_values if value)
    image = _media_path(_as_text(tour.get("hero_image") or tour.get("seo_image")), upload_dir)

    def draw_footer(c: canvas.Canvas, doc) -> None:
        c.saveState()
        c.setStrokeColor(LINE)
        c.line(MARGIN, 25, PAGE_W - MARGIN, 25)
        c.setFillColor(MUTED)
        c.setFont(FONT_REGULAR, 7)
        _fit_text(c, footer_text, MARGIN, 13, content_width - 45, FONT_REGULAR, 7, min_size=5.8)
        c.setFont(FONT_REGULAR, 7)
        c.drawRightString(PAGE_W - MARGIN, 13, f"Страница {doc.page}")
        c.restoreState()

    def draw_first_page(c: canvas.Canvas, doc) -> None:
        _draw_cover_image(c, image, 0, PAGE_H - 150, PAGE_W, 150)
        c.saveState()
        c.setFillColor(colors.Color(0, 0, 0, alpha=0.42))
        c.rect(0, PAGE_H - 150, PAGE_W, 150, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 13)
        c.drawString(MARGIN, PAGE_H - 24, default_company)

        title_size = 20.5
        title_lines = _wrap_text(title, FONT_BOLD, title_size, content_width)
        while len(title_lines) > 4 and title_size > 14:
            title_size -= 1
            title_lines = _wrap_text(title, FONT_BOLD, title_size, content_width)
        title_y = PAGE_H - 65
        c.setFont(FONT_BOLD, title_size)
        for line in title_lines:
            c.drawString(MARGIN, title_y, line)
            title_y -= title_size * 1.14
        c.restoreState()
        draw_footer(c, doc)

    def draw_later_page(c: canvas.Canvas, doc) -> None:
        c.saveState()
        c.setFillColor(ORANGE_DARK)
        c.setFont(FONT_BOLD, 8.5)
        c.drawString(MARGIN, PAGE_H - 22, default_company)
        c.setFillColor(MUTED)
        c.setFont(FONT_REGULAR, 7.5)
        compact_title = _truncate_words(title, 95)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 22, compact_title)
        c.setStrokeColor(LINE)
        c.line(MARGIN, PAGE_H - 29, PAGE_W - MARGIN, PAGE_H - 29)
        c.restoreState()
        draw_footer(c, doc)

    document = BaseDocTemplate(
        buffer,
        pagesize=A4,
        title=title,
        author=default_company,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=36,
        bottomMargin=footer_height,
    )
    first_frame = Frame(
        MARGIN,
        footer_height,
        content_width,
        PAGE_H - first_top - footer_height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="first-page-content",
    )
    later_frame = Frame(
        MARGIN,
        footer_height,
        content_width,
        PAGE_H - 66 - footer_height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="later-page-content",
    )
    document.addPageTemplates(
        [
            PageTemplate(
                id="First",
                frames=[first_frame],
                onPage=draw_first_page,
                autoNextPageTemplate="Later",
            ),
            PageTemplate(id="Later", frames=[later_frame], onPage=draw_later_page),
        ]
    )

    story: list = []
    intro = program_config.get("intro") or tour.get("tagline") or tour.get("short_description")
    _append_rich(story, intro, styles["intro"])
    description = tour.get("description")
    if _pdf_plain(description) and _pdf_plain(description) != _pdf_plain(intro):
        story.append(Paragraph("О туре", styles["section"]))
        _append_rich(story, description, styles["body"])

    facts = [
        ["Длительность", "Выезд", "Направление", "Стоимость"],
        [
            _pdf_plain(tour.get("duration")) or "уточняйте",
            _departure_cities(tour),
            _pdf_plain(tour.get("region_name")) or "уточняйте",
            _effective_price(tour),
        ],
    ]
    story.append(Spacer(1, 3))
    story.append(_styled_table(facts, [content_width / 4] * 4, styles))
    story.append(Spacer(1, 3))

    date_rows = _date_rows(tour)
    if date_rows:
        story.append(Paragraph("Даты и стоимость", styles["section"]))
        has_named_options = any(_pdf_plain(row[1]) for row in date_rows)
        if has_named_options:
            table_rows = [["Даты", "Вариант", "Стоимость"]] + date_rows
            table_widths = [
                content_width * 0.25,
                content_width * 0.45,
                content_width * 0.30,
            ]
        else:
            table_rows = [["Даты", "Стоимость"]] + [
                [row[0], row[2]] for row in date_rows
            ]
            table_widths = [content_width * 0.38, content_width * 0.62]
        story.append(
            _styled_table(
                table_rows,
                table_widths,
                styles,
            )
        )

    for heading, key in (
        ("Главные впечатления", "highlights"),
        ("Что увидим", "what_to_see"),
    ):
        values = tour.get(key)
        if isinstance(values, list) and any(_pdf_plain(item) for item in values):
            story.append(Paragraph(heading, styles["section"]))
            _append_bullets(story, values, styles["bullet"])

    days = program_config.get("days") if isinstance(program_config.get("days"), list) else tour.get("program")
    days = [day for day in (days or []) if isinstance(day, dict)]
    if days:
        story.append(Paragraph("Программа тура", styles["section"]))
        for index, day in enumerate(days, start=1):
            day_number = _pdf_plain(day.get("day")) or str(index)
            day_title = _pdf_plain(day.get("title")) or f"День {day_number}"
            story.append(
                Paragraph(
                    f"День {xml_escape(day_number)}. {xml_escape(day_title)}",
                    styles["subsection"],
                )
            )
            _append_rich(
                story,
                day.get("description") or day.get("notes"),
                styles["body"],
            )
            notes = day.get("notes")
            if _pdf_plain(notes) and _pdf_plain(notes) != _pdf_plain(day.get("description")):
                story.append(
                    Paragraph(
                        f"Важно: {xml_escape(_pdf_plain(notes), quote=False)}",
                        styles["body"],
                    )
                )
            if index < len(days):
                story.append(
                    HRFlowable(
                        width="100%",
                        thickness=0.45,
                        color=LINE,
                        spaceBefore=1,
                        spaceAfter=3,
                    )
                )

    source_lists = {
        "included": program_config.get("included", tour.get("included")),
        "excluded": program_config.get("excluded", tour.get("excluded")),
        "important_info": program_config.get("important_info", tour.get("important_info")),
    }
    for heading, key in (
        ("В стоимость включено", "included"),
        ("Оплачивается отдельно", "excluded"),
        ("Важная информация", "important_info"),
    ):
        values = source_lists[key]
        if isinstance(values, list) and any(_pdf_plain(item) for item in values):
            story.append(Paragraph(heading, styles["section"]))
            _append_bullets(story, values, styles["bullet"])

    _append_accommodation(story, tour, styles, content_width)

    faq = [item for item in tour.get("faq") or [] if isinstance(item, dict)]
    if faq:
        story.append(Paragraph("Частые вопросы", styles["section"]))
        for item in faq:
            question = _pdf_plain(item.get("question"))
            answer = item.get("answer")
            if question:
                story.append(Paragraph(xml_escape(question), styles["subsection"]))
            _append_rich(story, answer, styles["body"])

    if not story:
        story.append(Paragraph("Подробная программа уточняется у менеджера.", styles["body"]))

    document.build(story)
    return buffer.getvalue()
