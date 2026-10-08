# -*- coding: utf-8 -*-
"""Тесты Бот-Бортжурнала (Этап 4.4): quick-интерпретатор, разборы, per-chat kv."""

from datetime import date

import pytest

from telegram_bots.common import parsers
from telegram_bots.common.config_store import ConfigStore
from telegram_bots.vehicle_bot.quick import interpret


@pytest.fixture
def store(tmp_path):
    s = ConfigStore(str(tmp_path / "kv.db"))
    yield s
    s.close()


# --- ConfigStore kv -------------------------------------------------------

def test_kv_roundtrip(store):
    store.set_kv("1", "vehicle", "abc")
    assert store.get_kv("1", "vehicle") == "abc"
    store.set_kv("1", "vehicle", None)  # удаление
    assert store.get_kv("1", "vehicle") is None


def test_kv_isolation(store):
    store.set_kv("1", "vehicle", "x")
    assert store.get_kv("2", "vehicle") is None


# --- parsers --------------------------------------------------------------

def test_parsers_numbers_and_money():
    assert parsers.to_number("40,5") == 40.5
    assert parsers.to_money("2500р") == 2500
    assert parsers.to_odometer("пробег 125 000") == 125000
    assert parsers.to_int("40") == 40


def test_parsers_bool_and_date():
    assert parsers.to_bool("да") is True
    assert parsers.to_bool("нет") is False
    with pytest.raises(ValueError):
        parsers.to_bool("может")
    assert parsers.to_date("сегодня", date(2026, 10, 1)) == "2026-10-01"
    assert parsers.to_date("завтра", date(2026, 10, 1)) == "2026-10-02"
    with pytest.raises(ValueError):
        parsers.to_date("абракадабра")


# --- interpret (ТЗ 7.6 MVP) -----------------------------------------------

def test_interpret_fuel_full_sentence():
    r = interpret("Заправил 40л 95го на Лукойле 2500р пробег 125000",
                  today=date(2026, 10, 1), stations=["Лукойл", "Газпромнефть"])
    assert r and r["action"] == "create_fuel"
    p = r["payload"]
    assert p["volume_liters"] == 40
    assert p["total_cost"] == 2500
    assert p["fuel_type"] == "95"
    assert p["station_name"] == "Лукойл"
    assert p["odometer"] == 125000


def test_interpret_purchase():
    r = interpret("Купил масло 5W30 за 1500р", today=date(2026, 10, 1))
    assert r["action"] == "create_purchase"
    assert r["payload"]["amount"] == 1500


def test_interpret_fine():
    r = interpret("Штраф ГИБДД 500 рублей", today=date(2026, 10, 1))
    assert r["action"] == "create_fine"
    assert r["payload"]["amount"] == 500


def test_interpret_service():
    r = interpret("Был на сервисе, замена колодок 8000р", today=date(2026, 10, 1))
    assert r["action"] == "create_service"
    assert r["payload"]["amount"] == 8000


def test_interpret_fuel_requires_sum_and_liters():
    assert interpret("Заправил 40л 95", today=date(2026, 10, 1)) is None


def test_interpret_ambiguous_returns_none():
    assert interpret("привет как дела") is None
