# -*- coding: utf-8 -*-
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.vehicles.models import Purchase, PurchaseCategory, Vehicle


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


def create_purchase(vehicle, category=None, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        title="Комплект шин",
        amount=Decimal("42000.00"),
        purchase_date="2026-08-01",
        odometer=152300,
        items=[{"name": "Шины", "price": "42000.00", "qty": 4}],
    )
    data.update(kwargs)
    if category:
        data["category"] = category
    return Purchase.objects.create(**data)


@pytest.mark.django_db
def test_purchase_tab_shows_entry(client, user, vehicle, category):
    p = create_purchase(vehicle, category)
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert p.title in content
    assert "42000" in content
    assert category.name in content


@pytest.mark.django_db
def test_create_purchase(client, user, vehicle, category):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:purchase_create", args=[vehicle.pk]),
        {
            "vehicle": vehicle.pk,
            "purchase_date": "2026-08-01",
            "category": category.pk,
            "title": "Коврики салона",
            "amount": "4800.00",
            "odometer": "148200",
            "items_json": json.dumps([{"name": "Коврики", "price": "4800", "qty": 1}]),
            "description": "резина",
        },
    )
    assert response.status_code == 302
    p = Purchase.objects.get(vehicle=vehicle)
    assert p.title == "Коврики салона"
    assert p.amount == Decimal("4800.00")
    assert p.category == category
    assert p.odometer == 148200
    assert p.items == [{"name": "Коврики", "price": "4800", "qty": 1}]
    assert p.user == user


@pytest.mark.django_db
def test_create_purchase_negative_amount(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:purchase_create", args=[vehicle.pk]),
        {
            "vehicle": vehicle.pk,
            "purchase_date": "2026-08-01",
            "title": "Ошибка",
            "amount": "-100",
            "odometer": "0",
        },
    )
    assert response.status_code == 200
    assert "Сумма" in response.content.decode("utf-8")
    assert not Purchase.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_purchase_invalid_items_json(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:purchase_create", args=[vehicle.pk]),
        {
            "vehicle": vehicle.pk,
            "purchase_date": "2026-08-01",
            "title": "Покупка",
            "amount": "100",
            "items_json": "не-json",
        },
    )
    assert response.status_code == 200
    assert not Purchase.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_update_purchase(client, user, vehicle, category):
    p = create_purchase(vehicle, category)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:purchase_update", args=[vehicle.pk, p.pk]),
        {
            "vehicle": vehicle.pk,
            "purchase_date": "2026-08-05",
            "category": "",
            "title": "Мойка",
            "amount": "800.00",
            "odometer": "148500",
            "items_json": "[]",
            "description": "обновлено",
        },
    )
    assert response.status_code == 302
    p.refresh_from_db()
    assert p.title == "Мойка"
    assert p.amount == Decimal("800.00")
    assert p.category is None
    assert p.description == "обновлено"


@pytest.mark.django_db
def test_soft_delete_purchase(client, user, vehicle):
    p = create_purchase(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:purchase_delete", args=[vehicle.pk, p.pk]))
    assert response.status_code == 302
    p.refresh_from_db()
    assert p.is_deleted is True
    assert not Purchase.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_purchase_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    p = create_purchase(vehicle)
    client.force_login(other)
    assert (
        client.get(reverse("vehicles:purchase_create", args=[vehicle.pk])).status_code
        == 404
    )
    assert (
        client.get(
            reverse("vehicles:purchase_update", args=[vehicle.pk, p.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("vehicles:purchase_delete", args=[vehicle.pk, p.pk])
        ).status_code
        == 404
    )
    assert Purchase.objects.get(pk=p.pk).is_deleted is False


@pytest.mark.django_db
def test_purchase_summary_service(vehicle, category):
    from apps.vehicles import services

    create_purchase(vehicle, category, amount=Decimal("42000.00"))
    create_purchase(vehicle, amount=Decimal("4800.00"))
    summary = services.purchase_summary(vehicle.pk)
    assert summary["count"] == 2
    assert summary["total"] == Decimal("46800.00")
    assert len(summary["by_category"]) == 1
    assert summary["by_category"][0]["name"] == category.name
