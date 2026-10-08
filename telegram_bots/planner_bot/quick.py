"""Интерпретатор ``/quick`` для Записной книжки (ТЗ 7.6 этап 1).

text → {action, payload}. Встреча/событие — если есть время или слова-маркеры;
иначе — задача. Извлекаются дата/время, `#теги`, приоритет и место («в офисе»).
"""

from __future__ import annotations

import re
from datetime import date

from telegram_bots.common.quick_parser import parse_datetime, parse_tags

_EVENT_WORDS = ("встреч", "созвон", "день рождения", "свадьб", "приём", "прием",
                "визит", "свидан", "отпуск", "поздрав")
_LOCATION_RE = re.compile(r"\s(?:в|на)\s+([а-яёa-z]{3,})", re.IGNORECASE)
_TAG_STRIP_RE = re.compile(r"#\w+")


def _clean_title(text: str) -> str:
    title = _TAG_STRIP_RE.sub("", text)
    title = re.sub(r"\s+", " ", title).strip(" ,-.")
    return title


def _priority(low: str) -> str:
    if any(w in low for w in ("срочно", "немедленно", "срочн")):
        return "urgent"
    if any(w in low for w in ("важно", "ответств")):
        return "high"
    return "normal"


def interpret(text: str, today: date | None = None) -> dict | None:
    if not text or not text.strip():
        return None
    today = today or date.today()
    low = text.lower()
    dt = parse_datetime(text, today)
    tags = parse_tags(text)
    priority = _priority(low)
    title = _clean_title(text) or text.strip()

    has_time = bool(dt and (dt.hour or dt.minute)) or bool(re.search(r"\d{1,2}[:.]\d{2}", text))
    is_event = has_time or any(w in low for w in _EVENT_WORDS)

    if is_event:
        payload = {"title": title, "priority": priority}
        if dt:
            payload["start_at"] = dt.isoformat()
        loc = _LOCATION_RE.search(text)
        if loc:
            payload["location"] = loc.group(1).capitalize()
        if tags:
            payload["tags"] = tags
        return {"action": "create_event", "payload": payload}

    payload = {"title": title, "priority": priority}
    if dt:
        payload["due_at"] = dt.isoformat()
    if tags:
        payload["tags"] = tags
    return {"action": "create_task", "payload": payload}
