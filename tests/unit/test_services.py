# -*- coding: utf-8 -*-
"""Прямые unit-тесты бизнес-сервис-слоя Бортжурнала (apps.vehicles.services)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.references.models import CarBrand, CarModel, FuelStation
from apps.vehicles import services
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    PlannedEvent,
    Purchase,
    PurchaseCategory,
    Service,
    Vehicle,
)


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def other(db):
    return User.objects.create_user(email="other@test.ru", password="pass12345")


@pytest.fixture
def brand(db):
    return CarBrand.objects.create(name="Toyota", is_system=True, is_active=True)


@pytest.fixture
def car_model(db, brand):
    return CarModel.objects.create(brand=brand, name="Camry", is_system=True)


@pytest.fixture
def vehicle(db, user, brand, car_model):
    return Vehicle.objects.create(
        user=user,
        brand=brand,
        model=car_model,
        current_mileage=150000,
        is_default=True,
    )


# --- owned_queryset / get_owned (защита от IDOR) ---


@pytest.mark.django_db
def test_owned_queryset_filters_user_and_deleted(user, other, vehicle):
    Vehicle.objects.create(user=other)
    deleted = Vehicle.objects.create(user=user)
    deleted.delete()
    assert set(services.owned_queryset(Vehicle, user).values_list("pk", flat=True)) == {
        vehicle.pk
    }


@pytest.mark.django_db
def test_owned_queryset_raises_for_model_without_user(user):
    with pytest.raises(ValueError):
        services.owned_queryset(CarBrand, user)


@pytest.mark.django_db
def test_get_owned_returns_entity(user, vehicle):
    assert services.get_owned(Vehicle, user, vehicle.pk).pk == vehicle.pk


@pytest.mark.django_db
def test_get_owned_rejects_foreign_and_deleted(user, other, vehicle):
    with pytest.raises(Vehicle.DoesNotExist):
        services.get_owned(Vehicle, other, vehicle.pk)
    deleted = Vehicle.objects.create(user=user)
    deleted.delete()
    with pytest.raises(Vehicle.DoesNotExist):
        services.get_owned(Vehicle, user, deleted.pk)


@pytest.mark.django_db
def test_vehicle_belongs_to_user(user, other, vehicle):
    assert services.vehicle_belongs_to_user(vehicle, user) is True
    deleted = Vehicle.objects.create(user=user)
    deleted.delete()
    assert services.vehicle_belongs_to_user(deleted, user) is False
    assert services.vehicle_belongs_to_user(vehicle, other) is False


# --- автомобили ---


@pytest.mark.django_db
def test_set_default_vehicle_switches_flag(user, brand, car_model, vehicle):
    other_v = Vehicle.objects.create(user=user, brand=brand, model=car_model)
    services.set_default_vehicle(user, other_v)
    vehicle.refresh_from_db()
    other_v.refresh_from_db()
    assert other_v.is_default is True
    assert vehicle.is_default is False


@pytest.mark.django_db
def test_get_latest_odometer_max_across_entities(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=152000, total_cost=Decimal("0"),
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title="Шины",
        odometer=155000, purchase_date=date(2026, 8, 2),
    )
    Service.objects.create(
        user=user, vehicle=vehicle, work_description="ТО",
        odometer=156000, service_date=date(2026, 8, 3),
    )
    assert services.get_latest_odometer(vehicle.pk) == 156000


@pytest.mark.django_db
def test_recalc_vehicle_mileage_updates(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=180000, total_cost=Decimal("0"),
    )
    services.recalc_vehicle_mileage(str(vehicle.pk))
    vehicle.refresh_from_db()
    assert vehicle.current_mileage == 180000


@pytest.mark.django_db
def test_recalc_vehicle_mileage_keeps_value_without_entries(user, vehicle):
    services.recalc_vehicle_mileage(vehicle)
    vehicle.refresh_from_db()
    assert vehicle.current_mileage == 150000


# --- заправки ---


@pytest.mark.django_db
def test_resolve_fuel_station_creates_user_station(user, vehicle):
    entry = FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=150000, station_custom_name="Роснефть",
    )
    services.resolve_fuel_station(entry, user)
    assert entry.station is not None
    assert entry.station.name == "Роснефть"
    assert entry.station.created_by == user
    assert entry.station_custom_name == ""


@pytest.mark.django_db
def test_resolve_fuel_station_reuses_system_station(user, vehicle):
    station = FuelStation.objects.create(name="Лукойл", is_system=True)
    entry = FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=150000, station_custom_name="лукойл",
    )
    services.resolve_fuel_station(entry, user)
    assert entry.station == station
    assert entry.station_custom_name == ""


@pytest.mark.django_db
def test_attach_consumption_and_consumption_history(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=100000, volume_liters=Decimal("40.00"),
        full_tank=True, total_cost=Decimal("0"),
    )
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 5),
        odometer=100400, volume_liters=Decimal("60.00"),
        full_tank=True, total_cost=Decimal("0"),
    )
    entries = list(FuelEntry.objects.filter(vehicle=vehicle))
    services.attach_consumption(entries)
    by_pk = {e.pk: e for e in entries}
    by_odometer = {e.odometer: e for e in entries}
    assert by_pk[by_odometer[100000].pk].consumption is None
    assert by_pk[by_odometer[100400].pk].consumption == Decimal("15.0")

    history = services.consumption_history(vehicle.pk, months=3)
    assert len(history) == 1
    assert history[0]["month"] == "2026-08"
    assert history[0]["consumption"] == 15.0


@pytest.mark.django_db
def test_fuel_summary_empty(vehicle):
    summary = services.fuel_summary(vehicle.pk)
    assert summary["total_cost"] == 0
    assert summary["total_liters"] == 0
    assert summary["avg_price"] is None
    assert summary["avg_consumption"] is None
    assert summary["cost_per_km"] is None


@pytest.mark.django_db
def test_recent_fuel_stations_order_and_limit(user, vehicle):
    old = FuelStation.objects.create(name="Старая", created_by=user)
    newest = FuelStation.objects.create(name="Новая", created_by=user)
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 1, 1),
        odometer=100000, station=old, total_cost=Decimal("0"),
    )
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=150000, station=newest, total_cost=Decimal("0"),
    )
    stations = services.recent_fuel_stations(user)
    assert list(stations) == [newest, old]


@pytest.mark.django_db
def test_recent_fuel_stations_skips_without_station(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1),
        odometer=150000, total_cost=Decimal("0"),
    )
    assert services.recent_fuel_stations(user) == []


# --- штрафы: синхронизация с расходами ---


@pytest.mark.django_db
def test_sync_fine_purchase_creates_then_updates_purchase(user, vehicle):
    PurchaseCategory.objects.create(name="Штрафы", is_system=True)
    fine = Fine.objects.create(
        user=user, vehicle=vehicle, status="paid", amount=Decimal("2500.00"),
        description="Нарушение",
        fine_date=date(2026, 8, 1), paid_at=date(2026, 8, 2),
    )
    fine = services.sync_fine_purchase(fine, user, link=True)
    fine.refresh_from_db()
    purchase = fine.purchase
    assert purchase is not None
    assert purchase.title == "Нарушение"
    assert purchase.amount == Decimal("2500.00")
    assert purchase.category is not None
    assert purchase.category.name == "Штрафы"

    fine.description = "Нарушение (обжаловано)"
    fine.amount = Decimal("1000.00")
    fine.save()
    fine = services.sync_fine_purchase(fine, user, link=True)
    purchase.refresh_from_db()
    assert purchase.title == "Нарушение (обжаловано)"
    assert purchase.amount == Decimal("1000.00")
    assert Fine.objects.get(pk=fine.pk).purchase_id == purchase.pk
    assert Purchase.objects.filter(vehicle=vehicle, is_deleted=False).count() == 1


@pytest.mark.django_db
def test_sync_fine_purchase_unlinks_and_soft_deletes(user, vehicle):
    PurchaseCategory.objects.create(name="Штрафы", is_system=True)
    fine = Fine.objects.create(
        user=user, vehicle=vehicle, status="paid", amount=Decimal("100.00"),
        fine_date=date(2026, 8, 1),
    )
    fine = services.sync_fine_purchase(fine, user, link=True)
    fine.refresh_from_db()
    purchase = fine.purchase
    fine.status = "unpaid"
    fine.save()
    fine = services.sync_fine_purchase(fine, user, link=True)
    fine.refresh_from_db()
    purchase.refresh_from_db()
    assert fine.purchase is None
    assert purchase.is_deleted is True


# --- план: контекст карточек ---


@pytest.mark.django_db
def test_attach_plan_context_km_and_days(user, vehicle):
    e = PlannedEvent.objects.create(
        user=user, vehicle=vehicle, description="ТО",
        reminder_type="mileage", reminder_mileage=170000,
        planned_date=timezone.now() + timedelta(days=5),
    )
    services.attach_plan_context([e], current_mileage=165000)
    assert e.km_left == 5000
    assert e.days_left == 5


@pytest.mark.django_db
def test_attach_plan_context_missing_values(user, vehicle):
    e = PlannedEvent.objects.create(
        user=user, vehicle=vehicle, description="Без даты и пробега",
        reminder_type="date",
    )
    services.attach_plan_context([e], current_mileage=0)
    assert e.km_left is None
    assert e.days_left is None