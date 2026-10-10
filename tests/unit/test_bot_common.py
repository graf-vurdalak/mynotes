# -*- coding: utf-8 -*-
"""Тесты общего каркаса ботов (Этап 4.3): конфигурация инсталляций, парсер, тексты, клиент."""

import asyncio
from datetime import date
from unittest.mock import patch

import pytest
from aiogram.client.session.aiohttp import AiohttpSession

from telegram_bots.common import bot_runtime
from telegram_bots.common.api_client import BotAPIClient, BotAPIError
from telegram_bots.common.config_store import ConfigStore
from telegram_bots.common.quick_parser import (
    parse_date,
    parse_datetime,
    parse_fuel_type,
    parse_liters,
    parse_money,
    parse_odometer,
    parse_tags,
    parse_time,
)
from telegram_bots.common.texts import t


def test_create_bot_uses_configured_http_proxy(monkeypatch):
    proxy = "http://172.29.172.1:3128"
    monkeypatch.setenv("TELEGRAM_HTTP_PROXY", proxy)
    session = AiohttpSession()

    with patch.object(bot_runtime, "AiohttpSession", return_value=session) as session_factory:
        bot = bot_runtime.create_bot("123:secret")

    try:
        session_factory.assert_called_once_with(proxy=proxy)
        assert bot.session is session
    finally:
        asyncio.run(session.close())


# --- ConfigStore (мульти-серверность, ТЗ 7.1/7.2) --------------------------

@pytest.fixture
def store(tmp_path):
    s = ConfigStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def test_add_first_is_active(store):
    store.add("42", "prod", "Продакшн", "https://example.com/", "tok1")
    active = store.active("42")
    assert active and active.id == "prod"
    assert active.url == "https://example.com"  # слэш срезан
    assert active.is_active


def test_second_not_active_and_switch(store):
    store.add("42", "prod", "P", "https://a.example", "t1")
    store.add("42", "dev", "D", "https://b.example", "t2")
    assert store.active("42").id == "prod"
    assert store.set_active("42", "dev")
    assert store.active("42").id == "dev"


def test_set_active_unknown_returns_false(store):
    store.add("42", "prod", "P", "https://a.example", "t1")
    assert store.set_active("42", "nope") is False


def test_remove_fallback_activation(store):
    store.add("42", "prod", "P", "https://a.example", "t1")
    store.add("42", "dev", "D", "https://b.example", "t2")
    store.set_active("42", "dev")
    store.remove("42", "dev")
    assert store.active("42").id == "prod"


def test_isolation_between_chats(store):
    store.add("1", "a", "A", "https://a.example", "t")
    assert store.list("2") == []


def test_add_rejects_bad_url(store):
    with pytest.raises(ValueError):
        store.add("42", "x", "X", "ftp://bad", "t")


# --- quick_parser (ТЗ 7.6 этап 1) ------------------------------------------

def test_parse_money_volume_odometer():
    s = "Заправил 40л 95го на Лукойле 2500р пробег 125000"
    assert parse_money(s) == 2500
    assert parse_liters(s) == 40
    assert parse_odometer(s) == 125000
    assert parse_fuel_type(s) == "95"


def test_parse_money_with_thousands_and_symbol():
    assert parse_money("2 500 ₽") == 2500
    assert parse_money("150.5 руб") == 150.5


def test_parse_odometer_km_form():
    assert parse_odometer("пробег 125 000") == 125000
    assert parse_odometer("130 км") == 130


def test_parse_date_relative():
    today = date(2026, 10, 1)  # четверг
    assert parse_date("завтра", today) == date(2026, 10, 2)
    assert parse_date("сегодня", today) == date(2026, 10, 1)
    assert parse_date("в понедельник", today) == date(2026, 10, 5)


def test_parse_date_numeric_and_month():
    assert parse_date("15.08.2026") == date(2026, 8, 15)
    assert parse_date("15 августа", date(2026, 1, 1)) == date(2026, 8, 15)


def test_parse_time_and_datetime():
    assert parse_time("встреча в 15:00") == parse_time("15.00")
    dt = parse_datetime("завтра в 15:00", date(2026, 10, 1))
    assert dt.year == 2026 and dt.month == 10 and dt.day == 2 and dt.hour == 15


def test_parse_tags():
    assert parse_tags("отчёт #работа срочно #важное") == ["работа", "важное"]


# --- texts ------------------------------------------------------------------

def test_t_returns_key_when_missing():
    assert t("bot.__нет_такого__") == "bot.__нет_такого__"


def test_t_formats_placeholders():
    assert t("bot.addserver.added", name="Прод") == "Сервер «Прод» добавлен и проверен ✅"


# --- api_client -------------------------------------------------------------

def test_client_headers_and_url_normalization():
    c = BotAPIClient("https://example.com/", "secret-token")
    assert c.base_url == "https://example.com"
    assert c._headers() == {"X-Bot-Token": "secret-token"}


def test_client_chat_binding_headers():
    c = BotAPIClient("https://x", "t", chat_id=123, bot_name="vehicle")
    h = c._headers()
    assert h["X-Bot-Token"] == "t"
    assert h["X-Telegram-Chat-Id"] == "123"
    assert h["X-Bot-Name"] == "vehicle"


def test_bot_api_error_message():
    e = BotAPIError(401, "Invalid or inactive bot token")
    assert e.status == 401
    assert "401" in str(e) and "Invalid" in str(e)
