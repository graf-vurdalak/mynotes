"""Интерпретатор ``/quick`` для Бортжурнала (ТЗ 7.6 этап 1).

Чистая функция: текст → {action, payload} | None. Домен определяется ключевыми
словами, слоты заполняются общими примитивами ``quick_parser``; названия АЗС
подсвечиваются по переданному справочнику.
"""

from __future__ import annotations

from datetime import date

from telegram_bots.common.quick_parser import (
    parse_date,
    parse_fuel_type,
    parse_liters,
    parse_money,
    parse_odometer,
)

_FUEL_WORDS = ("заправ", "залил", "бензин", "солярк", "дизель")
_FINE_WORDS = ("штраф", "гибдд", "постановлен", "уин")
_SERVICE_WORDS = ("сервис", "сто", "заказ-наряд", "ремонт", "починил")
_PURCHASE_WORDS = ("купил", "купили", "запчасти", "масло", "фильтр", "шина", "диски")


def _match_station(text: str, stations: list[str]) -> str | None:
    low = text.lower()
    for name in stations:
        if name and name.lower() in low:
            return name
    return None


def interpret(text: str, today: date | None = None, stations: list[str] | None = None) -> dict | None:
    if not text or not text.strip():
        return None
    today = today or date.today()
    low = text.lower()
    amount = parse_money(text)
    liters = parse_liters(text)
    odometer = parse_odometer(text)
    fuel_type = parse_fuel_type(text)
    when = parse_date(text, today)
    station = _match_station(text, stations or [])

    if any(w in low for w in _FUEL_WORDS) or liters is not None or fuel_type is not None:
        _action = "create_fuel"
        payload = {"volume_liters": liters} if liters is not None else {}
        if amount is not None:
            payload["total_cost"] = amount
        if fuel_type:
            payload["fuel_type"] = fuel_type
        if station:
            payload["station_name"] = station
        if odometer is not None:
            payload["odometer"] = odometer
        if liters is None or amount is None:
            return None  # не хватает обязательных → перейти в мастер
        payload["fuel_date"] = (when or today).isoformat()
        return {"action": _action, "payload": payload}

    if any(w in low for w in _FINE_WORDS):
        if amount is None:
            return None
        return {"action": "create_fine", "payload": {
            "amount": amount, "description": text.strip(),
            "fine_date": (when or today).isoformat(),
        }}

    if any(w in low for w in _SERVICE_WORDS):
        if amount is None:
            return None
        payload = {"amount": amount, "work_description": text.strip(),
                   "service_date": (when or today).isoformat()}
        if odometer is not None:
            payload["odometer"] = odometer
        return {"action": "create_service", "payload": payload}

    if any(w in low for w in _PURCHASE_WORDS) or (amount is not None and station is None):
        if amount is None:
            return None
        payload = {"amount": amount, "title": text.strip(),
                   "purchase_date": (when or today).isoformat()}
        if odometer is not None:
            payload["odometer"] = odometer
        return {"action": "create_purchase", "payload": payload}

    return None
