# -*- coding: utf-8 -*-
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.references.models import FuelStation
from apps.vehicles.models import FuelEntry, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


@pytest.fixture
def station(db):
    return FuelStation.objects.create(name="Лукойл", is_system=True)


def create_entry(vehicle, station=None, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        fuel_date="2026-08-01",
        odometer=150000,
        fuel_type="ai95",
        volume_liters=Decimal("40.00"),
        price_per_liter=Decimal("63.00"),
        total_cost=Decimal("2520.00"),
        full_tank=True,
    )
    data.update(kwargs)
    if station:
        data["station"] = station
    return FuelEntry.objects.create(**data)


@pytest.mark.django_db
def test_fuel_tab_shows_entry(client, user, vehicle, station):
    create_entry(vehicle, station)
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Лукойл" in content
    assert "2520" in content


@pytest.mark.django_db
def test_create_fuel_entry_autocalc(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fuel_create", args=[vehicle.pk]),
        {
            "vehicle": vehicle.pk,
            "fuel_date": "2026-08-01",
            "station": "",
            "station_custom_name": "Роснефть",
            "fuel_type": "ai95",
            "odometer": "156000",
            "volume_liters": "40.00",
            "price_per_liter": "63.00",
            "full_tank": "on",
            "notes": "",
            "latitude": "",
            "longitude": "",
        },
    )
    assert response.status_code == 302
    entry = FuelEntry.objects.get(vehicle=vehicle)
    assert entry.total_cost == Decimal("2520.00")
    assert entry.volume_liters == Decimal("40.00")
    assert entry.full_tank is True
    assert entry.odometer == 156000

    entry.refresh_from_db()
    assert entry.station is not None
    assert entry.station.name == "Роснефть"
    assert entry.station_custom_name == ""
    assert entry.station.created_by == user


@pytest.mark.django_db
def test_create_fuel_entry_odometer_required(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fuel_create", args=[vehicle.pk]),
        {
            "vehicle": vehicle.pk,
            "fuel_date": "2026-08-01",
            "fuel_type": "ai95",
            "odometer": "-5",
            "volume_liters": "40.00",
            "price_per_liter": "63.00",
        },
    )
    assert response.status_code == 200
    assert "Пробег" in response.content.decode("utf-8")
    assert not FuelEntry.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_autocalc_service(client, user, vehicle):
    entry = create_entry(vehicle, volume_liters=Decimal("50"), price_per_liter=Decimal("60"))
    from apps.vehicles import services

    entry.total_cost = Decimal("0")
    entry = services.recalc_fuel_entry_totals(entry)
    assert entry.total_cost == Decimal("3000.00")


@pytest.mark.django_db
def test_update_fuel_entry(client, user, vehicle, station):
    entry = create_entry(vehicle, station)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fuel_update", args=[vehicle.pk, entry.pk]),
        {
            "vehicle": vehicle.pk,
            "fuel_date": "2026-08-05",
            "station": station.pk,
            "station_custom_name": "",
            "fuel_type": "ai92",
            "odometer": "156500",
            "volume_liters": "30.00",
            "price_per_liter": "61.00",
            "notes": "обновлено",
        },
    )
    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.fuel_date.strftime("%Y-%m-%d") == "2026-08-05"
    assert entry.fuel_type == "ai92"
    assert entry.notes == "обновлено"
    assert entry.total_cost == Decimal("1830.00")


@pytest.mark.django_db
def test_soft_delete_fuel_entry(client, user, vehicle):
    entry = create_entry(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:fuel_delete", args=[vehicle.pk, entry.pk]))
    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.is_deleted is True
    assert not FuelEntry.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_consumption_calculation(client, user, vehicle):
    from apps.vehicles import services

    prev = create_entry(vehicle, odometer=100000, volume_liters=Decimal("40"))
    entry = create_entry(vehicle, odometer=100400, volume_liters=Decimal("40"))
    assert compute_consumption(prev, entry) == Decimal("10.0")

    # неполный бак — расхода нет
    partial = create_entry(
        vehicle, odometer=105000, volume_liters=Decimal("20"), full_tank=False
    )
    assert compute_consumption(entry, partial) is None

    # средний за месяц по полным бакам
    summary = services.fuel_summary(vehicle.pk)
    assert summary["avg_consumption"] == Decimal("10.0")


def compute_consumption(prev, entry):
    from apps.vehicles.services import compute_fuel_consumption

    return compute_fuel_consumption(entry, prev)


@pytest.mark.django_db
def test_fuel_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    other_vehicle = Vehicle.objects.create(user=other)
    entry = create_entry(vehicle)
    client.force_login(other)
    assert client.get(reverse("vehicles:fuel_create", args=[vehicle.pk])).status_code == 404
    assert (
        client.get(reverse("vehicles:fuel_update", args=[vehicle.pk, entry.pk])).status_code
        == 404
    )
    assert (
        client.post(reverse("vehicles:fuel_delete", args=[vehicle.pk, entry.pk])).status_code
        == 404
    )
    assert FuelEntry.objects.get(pk=entry.pk).is_deleted is False
    assert client.get(reverse("vehicles:fuel_create", args=[other_vehicle.pk])).status_code == 200


@pytest.mark.django_db
def test_stations_api(client, user, station):
    client.force_login(user)
    response = client.get(reverse("vehicles:fuel_stations_api"), {"q": "Луко"})
    assert response.status_code == 200
    data = response.json()["stations"]
    assert any(s["name"] == "Лукойл" for s in data)
