"""Базовые примитивы быстрой записи ``/quick`` (ТЗ 7.6, этап 1).

Только регулярки + ключевые слова (без LLM): деньги, объём/литры, пробег, теги,
русские даты («завтра», «в понедельник», «15 августа», «15.08»), время («в 15:00»).
Интерпретация домена (заправка/покупка/событие/задача) — в парсерах конкретных ботов.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

MONEY_RE = re.compile(
    r"(\d[\d\s.,]*)\s*(?:₽|руб(?:лей|ля|ль)?|рубл(?:я|ь)?|usd|eur|kzt|uah|byn|грн|тг|р)(?!\w)",
    re.IGNORECASE,
)
LITERS_RE = re.compile(r"(\d[\d.,]*)\s*(?:л|литр(?:ов)?|l)\b", re.IGNORECASE)
ODO_RE = re.compile(r"(?:пробег|пр)\s*[:\-]?\s*(\d[\d\s]*)|(\d[\d\s]*)\s*(?:км|километр)", re.IGNORECASE)
TAG_RE = re.compile(r"#([\wа-яё]+)", re.IGNORECASE)
FUEL_NUM_RE = re.compile(r"(?<!\d)(92|95|98)(?!\d)")
FUEL_WORD_RE = re.compile(r"\b(дизель|электро|гибрид|газ|dt)\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(?:в\s*)?(\d{1,2})[:.\s](\d{2})\b")

WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
    "пятница": 4, "суббота": 5, "воскресенье": 6, "воскресение": 6,
}
MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "май": 5,
    "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
    "ноябр": 11, "декабр": 12,
}
NUM_DAY_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")


def _num(text: str) -> float:
    return float(re.sub(r"[^\d.,]", "", text).replace(" ", "").replace(",", "."))


def parse_money(text: str) -> float | None:
    m = MONEY_RE.search(text)
    return _num(m.group(1)) if m else None


def parse_liters(text: str) -> float | None:
    m = LITERS_RE.search(text)
    return _num(m.group(1)) if m else None


def parse_odometer(text: str) -> int | None:
    m = ODO_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    return int(re.sub(r"[^\d]", "", raw)) if raw else None


def parse_fuel_type(text: str) -> str | None:
    low = text.lower()
    m = FUEL_NUM_RE.search(low)
    if m:
        return m.group(1)
    m = FUEL_WORD_RE.search(low)
    if not m:
        return None
    return {
        "дизель": "diesel", "dt": "diesel", "электро": "electric",
        "гибрид": "hybrid", "газ": "gas",
    }[m.group(1)]


def parse_tags(text: str) -> list[str]:
    return TAG_RE.findall(text)


def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    low = text.lower()
    if "послезавтра" in low:
        return today + timedelta(days=2)
    if "завтра" in low:
        return today + timedelta(days=1)
    if "сегодня" in low:
        return today
    if "вчера" in low:
        return today - timedelta(days=1)
    for wd, idx in WEEKDAYS.items():
        if wd in low:
            delta = (idx - today.weekday()) % 7
            return today + timedelta(days=delta or 7)
    for stem, month in MONTHS.items():
        m = re.search(rf"(\d{{1,2}})\s+{stem}", low)
        if m:
            day = int(m.group(1))
            year = today.year
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if d < today:
                d = date(year + 1, month, day)
            return d
    m = NUM_DAY_RE.search(text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def parse_time(text: str) -> time | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None


def parse_datetime(text: str, today: date | None = None) -> datetime | None:
    d = parse_date(text, today)
    if d is None:
        return None
    tm = parse_time(text) or time(0, 0)
    return datetime.combine(d, tm)
