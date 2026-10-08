# -*- coding: utf-8 -*-
"""Unit-тесты моделей Бортжурнала, справочников и planner."""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.accounts.models import User
from apps.planner.models import Event
from apps.references.models import CarBrand, CarModel, FuelStation
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    PurchaseCategory,
    Service,
    ServicePhoto,
    Vehicle,
)


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


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


# --- OwnedModel: soft/hard delete ---


@pytest.mark.django_db
def test_delete_is_soft(user):
    v = Vehicle.objects.create(user=user, current_mileage=1000)
    v.delete()
    v.refresh_from_db()
    assert v.is_deleted is True
    assert Vehicle.objects.filter(user=user, is_deleted=False).count() == 0
    assert Vehicle.objects.filter(pk=v.pk).exists()


@pytest.mark.django_db
def test_hard_delete(user):
    v = Vehicle.objects.create(user=user, current_mileage=1000)
    v.hard_delete()
    assert not Vehicle.objects.filter(pk=v.pk).exists()


@pytest.mark.django_db
def test_owned_models_support_soft_delete(user, vehicle):
    entities = [
        FuelEntry.objects.create(
            user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1), odometer=1000
        ),
        Purchase.objects.create(user=user, vehicle=vehicle, title="Шины"),
        Service.objects.create(user=user, vehicle=vehicle, work_description="ТО"),
        Fine.objects.create(user=user, vehicle=vehicle, decision_number="12345678901234567890"),
        Insurance.objects.create(user=user, vehicle=vehicle, insurance_type="osago"),
        PlannedEvent.objects.create(user=user, vehicle=vehicle, description="Замена масла"),
    ]
    for e in entities:
        e.delete()
        e.refresh_from_db()
        assert e.is_deleted is True


# --- __str__ ---


@pytest.mark.django_db
def test_vehicle_str_from_catalog(brand, car_model, user):
    v = Vehicle.objects.create(user=user, brand=brand, model=car_model)
    assert str(v) == "Toyota Camry"


@pytest.mark.django_db
def test_vehicle_str_custom(user):
    v = Vehicle.objects.create(user=user, brand_custom="Lada", model_custom="Vesta")
    assert str(v) == "Lada Vesta"


@pytest.mark.django_db
def test_vehicle_str_empty_fields(user):
    v = Vehicle.objects.create(user=user)
    assert str(v) == str(v.id)


@pytest.mark.django_db
def test_entity_str(user, vehicle):
    fuel = FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1), odometer=1000
    )
    assert str(fuel) == "2026-08-01 / {}".format(vehicle.pk)

    p = Purchase.objects.create(user=user, vehicle=vehicle, title="Шины")
    assert str(p) == "Шины"

    s = Service.objects.create(user=user, vehicle=vehicle, work_description="ТО-60000")
    assert str(s) == "ТО-60000"

    f = Fine.objects.create(
        user=user, vehicle=vehicle, decision_number="18810177200718000123"
    )
    assert str(f) == "18810177200718000123"

    i = Insurance.objects.create(user=user, vehicle=vehicle, insurance_type="osago")
    assert str(i).startswith("ОСАГО")

    pl = PlannedEvent.objects.create(user=user, vehicle=vehicle, description="ТО-75000")
    assert str(pl) == "ТО-75000"

    cat = PurchaseCategory.objects.create(name="ТО и ремонт")
    assert str(cat) == "ТО и ремонт"


@pytest.mark.django_db
def test_service_photo_str_and_ordering(user, vehicle):
    s = Service.objects.create(user=user, vehicle=vehicle)
    p1 = ServicePhoto.objects.create(service=s, image="x1.png", sort_order=1)
    p2 = ServicePhoto.objects.create(service=s, image="x2.png", sort_order=2)
    assert list(s.photos.all()) == [p1, p2]
    assert str(p1) == "Фото x1.png"


# --- справочники ---


@pytest.mark.django_db
def test_car_brand_unique_name():
    CarBrand.objects.create(name="Toyota")
    with pytest.raises(IntegrityError):
        CarBrand.objects.create(name="Toyota")


@pytest.mark.django_db
def test_car_model_unique_per_brand(brand):
    CarModel.objects.create(brand=brand, name="Camry", is_system=True)
    with pytest.raises(IntegrityError):
        CarModel.objects.create(brand=brand, name="Camry")


@pytest.mark.django_db
def test_car_model_same_name_different_brand():
    b1 = CarBrand.objects.create(name="Brand A")
    b2 = CarBrand.objects.create(name="Brand B")
    CarModel.objects.create(brand=b1, name="X1")
    CarModel.objects.create(brand=b2, name="X1")
    assert CarModel.objects.filter(name="X1").count() == 2


@pytest.mark.django_db
def test_fuel_station_user_created(user):
    station = FuelStation.objects.create(name="Моя АЗС", created_by=user)
    assert station.is_system is False
    assert station.created_by == user
    assert str(station) == "Моя АЗС"


# --- прочее ---


@pytest.mark.django_db
def test_purchase_category_ordering():
    PurchaseCategory.objects.create(name="B", sort_order=2)
    PurchaseCategory.objects.create(name="A", sort_order=1)
    names = list(PurchaseCategory.objects.values_list("name", flat=True))
    assert names == ["A", "B"]


@pytest.mark.django_db
def test_planner_event_model(user):
    from apps.planner import services as planner_services

    scope = planner_services.get_scope(user, "personal")
    e = Event.objects.create(user=user, scope=scope, title="Замена масла")
    assert str(e) == "Замена масла"
    assert e.start_at is None
    assert e.tags == []
    assert list(Event.objects.filter(user=user)) == [e]


@pytest.mark.django_db
def test_defaults_on_entities(user, vehicle):
    fuel = FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=date(2026, 8, 1), odometer=1000
    )
    assert fuel.total_cost == Decimal("0")
    assert fuel.currency_code == "RUB"
    assert fuel.source == "web"

    p = Purchase.objects.create(user=user, vehicle=vehicle, title="Мойка")
    assert p.amount == Decimal("0")
    assert p.items == []

    f = Fine.objects.create(user=user, vehicle=vehicle)
    assert f.status == "unpaid"
    assert f.link_purchase is False

    i = Insurance.objects.create(user=user, vehicle=vehicle, start_date=date(2026, 8, 1))
    assert i.insurance_type == "osago"
    assert i.reminder_created is False

    pl = PlannedEvent.objects.create(user=user, vehicle=vehicle, description="Смена резины")
    assert pl.is_done is False
    assert pl.reminder_type == "date"