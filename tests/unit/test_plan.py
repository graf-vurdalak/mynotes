# -*- coding: utf-8 -*-
from datetime import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.vehicles.models import PlannedEvent, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


def _aware(year, month, day, hour=10):
    return timezone.make_aware(datetime(year, month, day, hour, 0))


def create_planned(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        description="Замена масла и фильтров",
        planned_date=_aware(2026, 8, 18),
        location="СТО «АвтоСервис», ул. Ленина, 45",
        estimated_cost=Decimal("12000.00"),
        reminder_type="date",
    )
    data.update(kwargs)
    return PlannedEvent.objects.create(**data)


def plan_form_post_data(vehicle, **overrides):
    data = dict(
        vehicle=vehicle.pk,
        description="Замена масла и фильтров",
        planned_date="2026-08-18T10:00",
        location="СТО «АвтоСервис», ул. Ленина, 45",
        estimated_cost="12000.00",
        reminder_type="date",
        reminder_mileage="",
    )
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_plan_tab_shows_event(client, user, vehicle):
    e = create_planned(vehicle)
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert e.description in content
    assert "СТО" in content
    assert "12000" in content


@pytest.mark.django_db
def test_plan_tab_empty_state_add_button(client, user, vehicle):
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert reverse("vehicles:plan_create", args=[vehicle.pk]) in content


@pytest.mark.django_db
def test_create_plan(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_create", args=[vehicle.pk]),
        plan_form_post_data(vehicle),
    )
    assert response.status_code == 302
    e = PlannedEvent.objects.get(vehicle=vehicle)
    assert e.description == "Замена масла и фильтров"
    assert e.location == "СТО «АвтоСервис», ул. Ленина, 45"
    assert e.estimated_cost == Decimal("12000.00")
    assert e.reminder_type == "date"
    assert e.is_done is False
    assert e.user == user


@pytest.mark.django_db
def test_create_plan_by_mileage(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_create", args=[vehicle.pk]),
        plan_form_post_data(
            vehicle,
            description="ТО-75000",
            reminder_type="mileage",
            reminder_mileage="75000",
            planned_date="",
            estimated_cost="25000.00",
        ),
    )
    assert response.status_code == 302
    e = PlannedEvent.objects.get(vehicle=vehicle)
    assert e.reminder_type == "mileage"
    assert e.reminder_mileage == 75000


@pytest.mark.django_db
def test_create_plan_mileage_requires_target(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_create", args=[vehicle.pk]),
        plan_form_post_data(vehicle, reminder_type="mileage", reminder_mileage=""),
    )
    assert response.status_code == 200
    assert not PlannedEvent.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_plan_negative_cost_rejected(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_create", args=[vehicle.pk]),
        plan_form_post_data(vehicle, estimated_cost="-100"),
    )
    assert response.status_code == 200
    assert not PlannedEvent.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_plan_cost_with_separators(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_create", args=[vehicle.pk]),
        plan_form_post_data(vehicle, estimated_cost="12 000,50"),
    )
    assert response.status_code == 302
    e = PlannedEvent.objects.get(vehicle=vehicle)
    assert e.estimated_cost == Decimal("12000.50")


@pytest.mark.django_db
def test_update_plan(client, user, vehicle):
    e = create_planned(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:plan_update", args=[vehicle.pk, e.pk]),
        plan_form_post_data(
            vehicle,
            description="Смена резины",
            location="Шиномонтаж",
            estimated_cost="4000",
            reminder_type="mileage",
            reminder_mileage="162000",
            is_done="on",
        ),
    )
    assert response.status_code == 302
    e.refresh_from_db()
    assert e.description == "Смена резины"
    assert e.location == "Шиномонтаж"
    assert e.estimated_cost == Decimal("4000.00")
    assert e.reminder_type == "mileage"
    assert e.reminder_mileage == 162000
    assert e.is_done is True


@pytest.mark.django_db
def test_soft_delete_plan(client, user, vehicle):
    e = create_planned(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:plan_delete", args=[vehicle.pk, e.pk]))
    assert response.status_code == 302
    e.refresh_from_db()
    assert e.is_deleted is True
    assert not PlannedEvent.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_plan_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    other_vehicle = Vehicle.objects.create(user=other)
    e = create_planned(vehicle)
    client.force_login(other)
    assert (
        client.get(reverse("vehicles:plan_create", args=[vehicle.pk])).status_code
        == 404
    )
    assert (
        client.get(
            reverse("vehicles:plan_update", args=[vehicle.pk, e.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("vehicles:plan_delete", args=[vehicle.pk, e.pk])
        ).status_code
        == 404
    )
    assert PlannedEvent.objects.get(pk=e.pk).is_deleted is False
    assert (
        client.get(reverse("vehicles:plan_create", args=[other_vehicle.pk])).status_code
        == 200
    )


@pytest.mark.django_db
def test_plan_filter_by_date(client, user, vehicle):
    create_planned(vehicle, reminder_type="date", planned_date=_aware(2026, 9, 1))
    create_planned(
        vehicle,
        description="ТО-75000",
        reminder_type="mileage",
        reminder_mileage=100000,
        planned_date=None,
    )
    client.force_login(user)
    response = client.get(
        reverse("vehicles:detail", args=[vehicle.pk]), {"plan_filter": "date"}
    )
    content = response.content.decode("utf-8")
    # событие по пробегу отфильтровано из списка; «ТО-75000» остаётся только
    # в блоке «Ближайшие» справа
    assert content.count("ТО-75000") == 1
    assert "Замена масла" in content


@pytest.mark.django_db
def test_planned_summary_service(vehicle, user):
    from apps.vehicles import services

    create_planned(vehicle, estimated_cost=Decimal("12000.00"), reminder_type="date")
    create_planned(
        vehicle,
        description="ТО-75000",
        estimated_cost=Decimal("25000.00"),
        reminder_type="mileage",
        reminder_mileage=75000,
        planned_date=None,
    )
    create_planned(
        vehicle,
        description="Смена резины",
        estimated_cost=Decimal("4000.00"),
        is_done=True,
        planned_date=_aware(2025, 4, 15),
    )
    summary = services.planned_summary(vehicle.pk, vehicle.current_mileage)
    assert summary["count"] == 3
    assert summary["pending_count"] == 2
    assert summary["budget"] == Decimal("37000.00")
    assert len(summary["nearest"]) <= 6