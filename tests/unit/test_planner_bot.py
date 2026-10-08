# -*- coding: utf-8 -*-
"""Тесты бота Записной книжки (Этап 4.5): quick-интерпретатор и datetime-разбор."""

from datetime import date

import pytest

from telegram_bots.common.parsers import to_datetime_field
from telegram_bots.planner_bot.quick import interpret


def test_interpret_event_with_time_and_location():
    r = interpret("Завтра в 15:00 встреча в офисе #работа", today=date(2026, 10, 1))
    assert r["action"] == "create_event"
    p = r["payload"]
    assert p["start_at"].startswith("2026-10-02T15:00")
    assert p["location"] == "Офисе"
    assert p["tags"] == ["работа"]


def test_interpret_task_default():
    r = interpret("Позвонить маме #дом", today=date(2026, 10, 1))
    assert r["action"] == "create_task"
    assert r["payload"]["tags"] == ["дом"]
    assert "due_at" not in r["payload"]


def test_interpret_task_priority_and_due():
    r = interpret("Сдать отчёт срочно до 5 декабря", today=date(2026, 10, 1))
    assert r["action"] == "create_task"
    assert r["payload"]["priority"] == "urgent"
    assert r["payload"]["due_at"].startswith("2026-12-05")


def test_interpret_empty_returns_none():
    assert interpret("   ") is None


# --- to_datetime_field ----------------------------------------------------

def test_dt_field_relative_and_iso():
    assert to_datetime_field("завтра", date(2026, 10, 1)) == "2026-10-02T00:00:00"
    assert to_datetime_field("завтра в 15:00", date(2026, 10, 1)) == "2026-10-02T15:00:00"
    assert to_datetime_field("2026-12-01") == "2026-12-01"


def test_dt_field_rejects_empty():
    for bad in ("/skip", "-", ""):
        with pytest.raises(ValueError):
            to_datetime_field(bad, date(2026, 10, 1))
