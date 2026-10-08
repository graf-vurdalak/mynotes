# -*- coding: utf-8 -*-
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.vehicles import services
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    Service,
    Vehicle,
)


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


def today():
    return timezone.localdate()


@pytest.mark.django_db
def test_dashboard_overview_default_vehicle_and_counts(user, vehicle):
    data = services.dashboard_overview(user)
    assert data["vehicle_count"] == 1
    assert data["default_vehicle"] == vehicle
    assert data["total_mileage"] == 150000


@pytest.mark.django_db
def test_dashboard_overview_monthly_expenses(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=today(), odometer=150000,
        volume_liters=Decimal("40"), total_cost=Decimal("2520.00"),
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title="Шины", amount=Decimal("42000.00"),
        purchase_date=today(),
    )
    Service.objects.create(
        user=user, vehicle=vehicle, work_description="ТО", amount=Decimal("5000.00"),
        service_date=today(),
    )
    data = services.dashboard_overview(user)
    assert data["fuel_month"] == Decimal("2520.00")
    assert data["fuel_liters"] == Decimal("40")
    assert data["expenses_month"] == Decimal("49520.00")


@pytest.mark.django_db
def test_dashboard_overview_ignores_other_month(user, vehicle):
    old = today() - timedelta(days=90)
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=old, total_cost=Decimal("9999.00"),
        volume_liters=Decimal("10"), odometer=149000,
    )
    data = services.dashboard_overview(user)
    assert data["fuel_month"] == Decimal("0")


@pytest.mark.django_db
def test_dashboard_overview_ignores_soft_deleted(user, vehicle):
    f = FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=today(),
        total_cost=Decimal("999.00"), volume_liters=Decimal("10"), odometer=150000,
    )
    f.delete()
    data = services.dashboard_overview(user)
    assert data["fuel_month"] == Decimal("0")


@pytest.mark.django_db
def test_dashboard_recent_events_sorted_and_limited(user, vehicle):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=today(), total_cost=Decimal("100"),
        odometer=150000,
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title="Покупка1", amount=Decimal("200"),
        purchase_date=today() - timedelta(days=1),
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title="Покупка2", amount=Decimal("300"),
        purchase_date=today() - timedelta(days=2),
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title="Покупка3", amount=Decimal("400"),
        purchase_date=today() - timedelta(days=3),
    )
    events = services._dashboard_recent_events(user, limit=3)
    assert len(events) == 3
    assert events[0]["kind"] == "fuel"  # самый свежий


@pytest.mark.django_db
def test_dashboard_overview_notifications_expiring_insurance(user, vehicle):
    Insurance.objects.create(
        user=user, vehicle=vehicle, insurance_type="osago",
        end_date=today() + timedelta(days=12),
    )
    data = services.dashboard_overview(user)
    assert len(data["expiring_insurances"]) == 1
    assert data["expiring_insurances"][0]["days_left"] == 12


@pytest.mark.django_db
def test_dashboard_overview_notifications_unpaid_fines(user, vehicle):
    Fine.objects.create(
        user=user, vehicle=vehicle, status="unpaid", amount=Decimal("500.00"),
        fine_date=today(),
    )
    Fine.objects.create(
        user=user, vehicle=vehicle, status="unpaid", amount=Decimal("1500.00"),
        fine_date=today(),
    )
    data = services.dashboard_overview(user)
    assert data["unpaid_fines_count"] == 2
    assert data["unpaid_fines_sum"] == Decimal("2000.00")


@pytest.mark.django_db
def test_dashboard_overview_ignores_paid_fines(user, vehicle):
    Fine.objects.create(
        user=user, vehicle=vehicle, status="paid", amount=Decimal("500.00"),
        fine_date=today(),
    )
    data = services.dashboard_overview(user)
    assert data["unpaid_fines_count"] == 0


@pytest.mark.django_db
def test_dashboard_overview_upcoming_planned(user, vehicle):
    PlannedEvent.objects.create(
        user=user, vehicle=vehicle,
        description="Замена масла",
        planned_date=timezone.now() + timedelta(days=2),
    )
    data = services.dashboard_overview(user)
    assert len(data["upcoming_planned"]) == 1
    assert data["upcoming_planned"][0]["description"] == "Замена масла"


@pytest.mark.django_db
def test_dashboard_overview_excludes_done_and_past_planned(user, vehicle):
    PlannedEvent.objects.create(
        user=user, vehicle=vehicle, description="Выполнено",
        planned_date=timezone.now() + timedelta(days=2), is_done=True,
    )
    PlannedEvent.objects.create(
        user=user, vehicle=vehicle, description="Прошлое",
        planned_date=timezone.now() - timedelta(days=2),
    )
    data = services.dashboard_overview(user)
    assert len(data["upcoming_planned"]) == 0


@pytest.mark.django_db
def test_dashboard_page_renders(client, user, vehicle):
    Fine.objects.create(
        user=user, vehicle=vehicle, status="unpaid", amount=Decimal("500.00"),
        fine_date=today(),
    )
    client.force_login(user)
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "500" in content


@pytest.mark.django_db
def test_dashboard_page_renders_empty_state(client, user):
    client.force_login(user)
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "fleet_empty" not in content


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    assert client.get(reverse("core:dashboard")).status_code == 302