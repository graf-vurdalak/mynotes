"""Утилиты inline-режима (ТЗ 7.5): разбор запроса и сборка результатов.

Чистые функции (без aiogram) возвращают list[dict] — удобно тестировать; боты
превращают их в ``InlineQueryResultArticle``. Inline-запрос не имеет контекста чата,
поэтому инсталляция ищется по ``from_user.id`` (тот же id, что у диалога 1:1).
"""

from __future__ import annotations

_PREFIXES = ("поиск", "search", "задача", "task", "событие", "event")


def parse_term(raw: str, prefixes=_PREFIXES) -> str:
    text = (raw or "").strip()
    for p in prefixes:
        if text.lower().startswith(p + ":"):
            return text[len(p) + 1:].strip()
        if text.lower().startswith(p + " "):
            return text[len(p) + 1:].strip()
    return text


def vehicle_results(records: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(records):
        label = "⛽" if r["kind"] == "fuel" else "🧾"
        out.append({
            "id": f"veh-{i}-{r['id']}",
            "title": f"{label} {r['title']}",
            "description": f"{r.get('date') or ''} · {r.get('detail') or ''}".strip(" ·"),
            "text": f"{r['title']} — {r.get('detail') or ''} · {r.get('date') or ''}".strip(),
        })
    return out


def planner_results(events: list[dict]) -> list[dict]:
    out = []
    for i, e in enumerate(events):
        when = (e.get("start") or "").replace("T", " ")[:16]
        out.append({
            "id": f"pln-{i}-{e['id']}",
            "title": e["title"],
            "description": f"{e.get('scope', '')} · {e.get('status') or ''}".strip(" ·"),
            "text": f"📌 {e['title']} · {when}".strip(" ·"),
        })
    return out
