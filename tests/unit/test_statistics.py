# -*- coding: utf-8 -*-
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    Insurance,
    Purchase,
    PurchaseCategory,
    Service,
    Vehicle,
)
from apps.vehicles import services


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


@pytest.fixture
def category(db):
    return PurchaseCategory.objects.create(
        name="ТО и ремонт", color="#10B981", is_system=True, sort_order=1
    )


def today():
    return timezone.localdate()


def create_fuel(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        fuel_date=today(),
        odometer=150000,
        volume_liters=Decimal("40.00"),
        price_per_liter=Decimal("63.00"),
        total_cost=Decimal("2520.00"),
        full_tank=True,
    )
    data.update(kwargs)
    return FuelEntry.objects.create(**data)


def create_purchase(vehicle, category=None, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        title="Комплект шин",
        amount=Decimal("42000.00"),
        purchase_date=today(),
    )
    data.update(kwargs)
    if category:
        data["category"] = category
    return Purchase.objects.create(**data)


def create_service(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        work_description="Замена масла",
        amount=Decimal("5000.00"),
        service_date=today(),
    )
    data.update(kwargs)
    return Service.objects.create(**data)


def create_fine(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        description="Превышение",
        amount=Decimal("3000.00"),
        fine_date=today(),
        status="unpaid",
    )
    data.update(kwargs)
    return Fine.objects.create(**data)


def create_insurance(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        insurance_type="osago",
        company="Альфа",
        cost=Decimal("5000.00"),
    )
    data.update(kwargs)
    return Insurance.objects.create(**data)


@pytest.mark.django_db
def test_monthly_cost_buckets_current_month(vehicle):
    create_fuel(vehicle, total_cost=Decimal("2520.00"))
    create_purchase(vehicle, amount=Decimal("42000.00"))
    monthly = services.monthly_cost(vehicle.pk, months=6)
    assert len(monthly) == 6
    last = monthly[-1]
    assert last["fuel"] == Decimal("2520.00")
    assert last["purchase"] == Decimal("42000.00")
    assert last["total"] == Decimal("44520.00")


@pytest.mark.django_db
def test_monthly_cost_ignores_date_outside_window(vehicle):
    import datetime

    old = datetime.date(2020, 1, 10)
    create_fuel(vehicle, fuel_date=old, total_cost=Decimal("1000.00"))
    monthly = services.monthly_cost(vehicle.pk, months=6)
    assert sum(m["fuel"] for m in monthly) == Decimal("0")


@pytest.mark.django_db
def test_expenses_by_category_sorted_and_groups(vehicle, category):
    create_fuel(vehicle, total_cost=Decimal("1000.00"))
    create_purchase(vehicle, category=category, amount=Decimal("2000.00"))
    create_service(vehicle, amount=Decimal("1500.00"))
    create_insurance(vehicle, cost=Decimal("500.00"))
    create_fine(vehicle, amount=Decimal("300.00"))
    cats = {c["key"]: c["total"] for c in services.expenses_by_category(vehicle.pk)}
    assert cats["fuel"] == Decimal("1000.00")
    assert cats["service"] == Decimal("1500.00")
    assert cats["insurance"] == Decimal("500.00")
    assert cats["fines"] == Decimal("300.00")
    purchase_key = next(k for k in cats if k.startswith("pur_"))
    assert cats[purchase_key] == Decimal("2000.00")


@pytest.mark.django_db
def test_stats_overview_kpi_and_top(vehicle, category):
    create_fuel(vehicle, total_cost=Decimal("1000.00"))
    create_purchase(vehicle, category=category, amount=Decimal("4000.00"))
    create_service(vehicle, amount=Decimal("500.00"))

    stats = services.stats_overview(vehicle.pk)
    assert stats["total_cost"] == Decimal("5500.00")
    assert stats["category_top"][0]["key"].startswith("pur_")
    assert len(stats["category_top"]) <= 5
    assert stats["total_display"] == Decimal("5.5")
    assert stats["consumption_max"] > 0
    # каждый элемент категории снабжён данными для кольцевой диаграммы
    for c in stats["categories"]:
        assert c["dash"] >= 0
        assert c["dashoffset"] <= 0


@pytest.mark.django_db
def test_stats_tab_renders_on_detail(client, user, vehicle, category):
    create_fuel(vehicle, total_cost=Decimal("2520.00"))
    create_purchase(vehicle, category=category, amount=Decimal("42000.00"))
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    # KPI «Расходы за период» содержит сумму
    assert "44520" in content
    # Статьи и диаграммы присутствуют
    assert "Топливо" in content
    assert category.name in content


@pytest.mark.django_db
def test_vehicle_list_per_car_summary_and_indicators(client, user, vehicle):
    create_fuel(vehicle, total_cost=Decimal("1000.00"))
    create_fine(vehicle, status="unpaid", amount=Decimal("500.00"))
    deadline = timezone.now().date()
    create_insurance(vehicle, end_date=deadline)

    client.force_login(user)
    response = client.get(reverse("vehicles:list"))
    assert response.status_code == 200
    context_vehicle = response.context["vehicles"][0]
    assert context_vehicle.unpaid_fines == 1
    assert context_vehicle.expiring_insurances >= 1
    assert context_vehicle.expired_insurances == 0
    assert context_vehicle.expenses_month == Decimal("1000.00")


@pytest.mark.django_db
def test_vehicle_list_expired_insurance_still_notified(client, user, vehicle):
    import datetime

    expired = timezone.localdate() - datetime.timedelta(days=5)
    create_insurance(vehicle, end_date=expired)

    client.force_login(user)
    response = client.get(reverse("vehicles:list"))
    assert response.status_code == 200
    ctx = response.context["vehicles"][0]
    assert ctx.expired_insurances == 1
    assert ctx.notice_count >= 1