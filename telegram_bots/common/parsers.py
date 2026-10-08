"""Разборчики ввода для мастеров: строка → типизированное значение / ValueError.

Значения JSON-safe (int/float/bool/str/None), чтобы мастера работали поверх любого
FSM-storage (MemoryStorage/Redis) и передавались в ``/api/v1/bot/ingest`` как payload.
"""

from __future__ import annotations

import re
from datetime import date

from .quick_parser import parse_date, parse_liters, parse_money, parse_odometer

_NUM_RE = re.compile(r"^\s*-?\d[\d\s.,]*\s*$")


def to_int(text: str) -> int:
    raw = re.sub(r"[^\d]", "", text)
    if not raw:
        raise ValueError("no digits")
    return int(raw)


def to_number(text: str) -> float:
    if not _NUM_RE.match(text):
        raise ValueError("not a number")
    return float(text.replace(" ", "").replace(",", "."))


def to_money(text: str) -> float:
    value = parse_money(text)
    if value is None:
        # допускаем просто число без валютного маркера
        return to_number(text)
    return value


def to_liters(text: str) -> float:
    if text.strip().lower() in ("-", "нет"):
        raise ValueError("empty")
    # просто число (без суффикса «л») тоже валидно
    if _NUM_RE.match(text):
        return to_number(text)
    return parse_liters(text)


def to_odometer(text: str) -> int:
    if _NUM_RE.match(text):
        return to_int(text)
    value = parse_odometer(text)
    if value is None:
        raise ValueError("no odometer")
    return value


def to_date(text: str, today: date | None = None) -> str:
    if text.strip().lower() in ("", "-", "сегодня", "today"):
        d = today or date.today()
        return d.isoformat()
    d = parse_date(text, today)
    if d is None:
        raise ValueError("bad date")
    return d.isoformat()


def to_datetime_field(text: str, today: date | None = None) -> str:
    """Строка → ISO datetime. Принимает и «завтра в 15:00», и «2026-12-01»."""
    from .quick_parser import parse_datetime

    raw = (text or "").strip()
    if raw in ("", "-", "нет", "/skip"):
        raise ValueError("empty")
    dt = parse_datetime(raw, today)
    if dt is not None:
        return dt.isoformat()
    # явный ISO date / datetime без слов-ключей
    if re.match(r"^\d{4}-\d{2}-\d{2}([T ]\d{1,2}:\d{2})?$", raw):
        return raw.replace(" ", "T")
    raise ValueError("bad datetime")


def to_bool(text: str) -> bool:
    t = text.strip().lower()
    if t in ("да", "yes", "y", "1", "full", "полный"):
        return True
    if t in ("нет", "no", "n", "0", "частичный"):
        return False
    raise ValueError("yes/no")


def to_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty")
    return text


def to_tags(text: str) -> list[str]:
    from .quick_parser import parse_tags

    tags = parse_tags(text)
    if not tags:
        # допускаем простой перечень через запятую без решёток
        tags = [t.strip().lstrip("#") for t in re.split(r"[,\s]+", text) if t.strip()]
    return tags
