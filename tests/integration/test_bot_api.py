# -*- coding: utf-8 -*-
"""Интеграционные тесты API-гейтвея для Telegram-ботов (Этап 4.2, ТЗ 6.2)."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import AuthToken
from apps.accounts.tokens import issue_token
from apps.vehicles.models import FuelEntry, Purchase, Service, Vehicle

User = get_user_model()

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


@pytest.fixture
def user(db):
    return User.objects.create_user(email="api@test.ru", password="pass12345")


@pytest.fixture
def token(user):
    plain, _ = issue_token(user, "тест")
    return plain


@pytest.fixture
def vehicle(user):
    return Vehicle.objects.create(
        user=user, brand_custom="Kia", model_custom="Rio", current_mileage=100000
    )


def hdr(token):
    return {"HTTP_X_BOT_TOKEN": token}


def ingest(client, token, module, action, payload=None):
    return client.post(
        "/api/v1/bot/ingest/",
        data=json.dumps({"module": module, "action": action, "payload": payload or {}}),
        content_type="application/json",
        **hdr(token),
    )


# --- ping / auth -----------------------------------------------------------

@pytest.mark.django_db
def test_ping_valid_token(client, token):
    r = client.post("/api/v1/bot/ping/", **hdr(token))
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.django_db
def test_ping_missing_token(client):
    assert client.post("/api/v1/bot/ping/").status_code == 401


@pytest.mark.django_db
def test_ping_bad_token(client, token):
    r = client.post("/api/v1/bot/ping/", **hdr("неверный-" + token))
    assert r.status_code == 401


@pytest.mark.django_db
def test_revoked_token_rejected(client, user, token):
    AuthToken.objects.filter(user=user).update(is_active=False)
    assert client.post("/api/v1/bot/ping/", **hdr(token)).status_code == 401


# --- ingest: vehicle writes ------------------------------------------------

@pytest.mark.django_db
def test_ingest_create_fuel_computes_total_and_mileage(client, token, vehicle):
    r = ingest(client, token, "vehicle", "create_fuel", {
        "vehicle_id": str(vehicle.id), "odometer": 100200,
        "volume_liters": "40", "price_per_liter": "55.5", "fuel_type": "95",
        "station_name": "Лукойл", "full_tank": True,
    })
    assert r.status_code == 200, r.content
    entry = FuelEntry.objects.get(pk=r.json()["entity_id"])
    assert entry.source == "telegram"
    assert entry.total_cost == 40 * 55.5
    assert entry.station is not None and entry.station.name == "Лукойл"
    vehicle.refresh_from_db()
    assert vehicle.current_mileage == 100200


@pytest.mark.django_db
def test_ingest_create_purchase(client, token, vehicle):
    r = ingest(client, token, "vehicle", "create_purchase", {
        "vehicle_id": str(vehicle.id), "title": "Масло", "amount": "1200",
    })
    assert r.status_code == 200
    p = Purchase.objects.get(pk=r.json()["entity_id"])
    assert p.title == "Масло" and str(p.amount) == "1200.00"


@pytest.mark.django_db
def test_ingest_unknown_action_400(client, token):
    r = ingest(client, token, "vehicle", "nope", {})
    assert r.status_code == 400


@pytest.mark.django_db
def test_ingest_missing_required_field_400(client, token, vehicle):
    r = ingest(client, token, "vehicle", "create_fuel",
               {"vehicle_id": str(vehicle.id)})
    assert r.status_code == 400


@pytest.mark.django_db
def test_ingest_idor_other_user_vehicle(client, token, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    _plain, _ = issue_token(other, "o")
    # токен второго пользователя не видит авто первого, и наоборот:
    other_vehicle = Vehicle.objects.create(user=other, brand_custom="BMW")
    r = ingest(client, token, "vehicle", "create_fuel", {
        "vehicle_id": str(other_vehicle.id), "odometer": 1, "volume_liters": "1",
    })
    assert r.status_code == 400


# --- ingest: planner writes ------------------------------------------------

@pytest.mark.django_db
def test_ingest_create_task_work_scope(client, token):
    from apps.planner.models import Event
    r = ingest(client, token, "planner", "create_task",
               {"title": "Отчёт", "priority": "high", "due_at": "2026-12-01T10:00:00"})
    assert r.status_code == 200
    ev = Event.objects.get(pk=r.json()["entity_id"])
    assert ev.scope.code == "work" and ev.event_type == "task"
    assert ev.source == "telegram" and ev.status.code == "new"


@pytest.mark.django_db
def test_ingest_create_event_personal(client, token):
    from apps.planner.models import Event
    r = ingest(client, token, "planner", "create_event",
               {"title": "Встреча", "start_at": "2026-12-01T15:00:00",
                "location": "Офис", "tags": ["работа"]})
    assert r.status_code == 200
    ev = Event.objects.get(pk=r.json()["entity_id"])
    assert ev.scope.code == "personal" and "работа" in ev.tags


# --- references ------------------------------------------------------------

@pytest.mark.django_db
def test_reference_vehicles(client, token, vehicle):
    r = client.get("/api/v1/bot/references/vehicles/", **hdr(token))
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()["data"]]
    assert str(vehicle.id) in ids


@pytest.mark.django_db
def test_reference_unknown_type_404(client, token):
    r = client.get("/api/v1/bot/references/nonsense/", **hdr(token))
    assert r.status_code == 404


@pytest.mark.django_db
def test_action_list_vehicles(client, token, vehicle):
    r = ingest(client, token, "vehicle", "list_vehicles")
    assert r.status_code == 200
    assert any(v["id"] == str(vehicle.id) for v in r.json()["data"])


# --- upload + service photos ----------------------------------------------

@pytest.mark.django_db
def test_upload_then_create_service_attaches_photo(client, token, vehicle):
    up = client.post("/api/v1/bot/upload/",
                     {"file": SimpleUploadedFile("x.png", PNG, content_type="image/png")},
                     **hdr(token))
    assert up.status_code == 200, up.content
    upload_id = up.json()["upload_id"]
    r = ingest(client, token, "vehicle", "create_service", {
        "vehicle_id": str(vehicle.id), "work_description": "Замена колодок",
        "amount": "3000", "upload_ids": [upload_id],
    })
    assert r.status_code == 200, r.content
    service = Service.objects.get(pk=r.json()["entity_id"])
    assert service.photos.count() == 1
    from apps.api.models import BotUpload
    assert BotUpload.objects.count() == 0  # staging удалён


@pytest.mark.django_db
def test_upload_rejects_html(client, token):
    bad = SimpleUploadedFile("evil.png", b"<html><script>x</script></html>",
                             content_type="image/png")
    r = client.post("/api/v1/bot/upload/", {"file": bad}, **hdr(token))
    assert r.status_code == 400
