# -*- coding: utf-8 -*-
"""Тесты inline-утилит (Этап 4.6, ТЗ 7.5) + action search_records гейтвея."""

import json

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.tokens import issue_token
from apps.vehicles.models import FuelEntry, Purchase, Vehicle
from telegram_bots.common.inline import parse_term, planner_results, vehicle_results

User = get_user_model()


# --- чистые утилиты -------------------------------------------------------

def test_parse_term_strips_prefixes():
    assert parse_term("поиск:Лукойл") == "Лукойл"
    assert parse_term("search: масло") == "масло"
    assert parse_term("задача: отчёт") == "отчёт"
    assert parse_term("просто запрос") == "просто запрос"


def test_vehicle_results_shape():
    rs = vehicle_results([{"id": "1", "kind": "fuel", "title": "Лукойл",
                           "date": "2026-10-01", "detail": "40л · 2500₽"}])
    assert len(rs) == 1
    assert rs[0]["id"].startswith("veh-0-")
    assert "Лукойл" in rs[0]["title"]


def test_planner_results_shape():
    rs = planner_results([{"id": "e1", "title": "Встреча", "scope": "personal",
                           "status": None, "start": "2026-10-02T15:00:00"}])
    assert rs[0]["id"].startswith("pln-0-")
    assert "15:00" in rs[0]["text"]


# --- гейтвей: vehicle/search_records -------------------------------------

@pytest.fixture
def user(db):
    return User.objects.create_user(email="inline@test.ru", password="pass12345")


@pytest.fixture
def token(user):
    plain, _ = issue_token(user, "тест")
    return plain


def hdr(token):
    return {"HTTP_X_BOT_TOKEN": token}


@pytest.mark.django_db
def test_search_records_action(client, token, user):
    v = Vehicle.objects.create(user=user, brand_custom="Kia", model_custom="Rio")
    FuelEntry.objects.create(user=user, vehicle=v, fuel_date="2026-10-01", odometer=100,
                             station_custom_name="Лукойл", volume_liters=40,
                             price_per_liter=50, total_cost=2000, source="telegram")
    Purchase.objects.create(user=user, vehicle=v, title="Масло 5W30", amount=1500,
                            purchase_date="2026-09-30", source="telegram")
    r = client.post(
        "/api/v1/bot/ingest/",
        data=json.dumps({"module": "vehicle", "action": "search_records",
                         "payload": {"query": "лукойл"}}),
        content_type="application/json", **hdr(token),
    )
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert any(x["kind"] == "fuel" for x in data)
    assert not any(x["kind"] == "purchase" for x in data)  # фильтр по термину


@pytest.mark.django_db
def test_search_records_empty_returns_recent(client, token, user):
    v = Vehicle.objects.create(user=user, brand_custom="Lada")
    FuelEntry.objects.create(user=user, vehicle=v, fuel_date="2026-10-01", odometer=10,
                             station_custom_name="Газпром", volume_liters=10,
                             price_per_liter=50, total_cost=500)
    r = client.post(
        "/api/v1/bot/ingest/",
        data=json.dumps({"module": "vehicle", "action": "search_records", "payload": {}}),
        content_type="application/json", **hdr(token),
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1
