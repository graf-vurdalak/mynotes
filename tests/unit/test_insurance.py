# -*- coding: utf-8 -*-
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.vehicles.models import Insurance, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


def make_png(name="insurance.png", size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, (100, 150, 200)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def create_insurance(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        insurance_type="osago",
        company="Росгосстрах",
        policy_number="XXX 0456789012",
        start_date="2026-08-01",
        end_date="2027-08-01",
        cost=Decimal("8500.00"),
        reminder_created=True,
    )
    data.update(kwargs)
    return Insurance.objects.create(**data)


def insurance_form_post_data(vehicle, **overrides):
    data = dict(
        vehicle=vehicle.pk,
        insurance_type="osago",
        company="Росгосстрах",
        policy_number="XXX 0456789012",
        start_date="2026-08-01",
        end_date="2027-08-01",
        cost="8500.00",
        reminder_created="on",
    )
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_insurance_tab_shows_policy(client, user, vehicle):
    i = create_insurance(vehicle)
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert i.policy_number in content
    assert "Росгосстрах" in content
    assert "8500" in content


@pytest.mark.django_db
def test_insurance_empty_state(client, user, vehicle):
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "insurance.empty_hint" not in content


@pytest.mark.django_db
def test_insurance_empty_state_add_button(client, user, vehicle):
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert reverse("vehicles:insurance_create", args=[vehicle.pk]) in content


@pytest.mark.django_db
def test_create_insurance(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        insurance_form_post_data(vehicle),
    )
    assert response.status_code == 302
    i = Insurance.objects.get(vehicle=vehicle)
    assert i.insurance_type == "osago"
    assert i.company == "Росгосстрах"
    assert i.policy_number == "XXX 0456789012"
    assert i.cost == Decimal("8500.00")
    assert i.reminder_created is True
    assert i.user == user


@pytest.mark.django_db
def test_create_insurance_no_reminder(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        insurance_form_post_data(vehicle, reminder_created=""),
    )
    assert response.status_code == 302
    i = Insurance.objects.get(vehicle=vehicle)
    assert i.reminder_created is False


@pytest.mark.django_db
def test_create_insurance_negative_cost_rejected(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        insurance_form_post_data(vehicle, cost="-100"),
    )
    assert response.status_code == 200
    assert "Стоимость" in response.content.decode("utf-8")
    assert not Insurance.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_insurance_end_before_start_rejected(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        insurance_form_post_data(vehicle, start_date="2027-01-01", end_date="2026-01-01"),
    )
    assert response.status_code == 200
    assert not Insurance.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_insurance_with_photo(client, user, vehicle):
    data = insurance_form_post_data(vehicle)
    data["photo"] = make_png()
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        data,
        format="multipart",
    )
    assert response.status_code == 302
    i = Insurance.objects.get(vehicle=vehicle)
    assert i.photo.name.endswith(".png")


@pytest.mark.django_db
def test_create_insurance_spoofed_photo_rejected(client, user, vehicle):
    data = insurance_form_post_data(vehicle)
    data["photo"] = SimpleUploadedFile(
        "evil.png", b"<script>alert(1)</script>", content_type="image/png"
    )
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_create", args=[vehicle.pk]),
        data,
        format="multipart",
    )
    assert response.status_code == 200
    assert not Insurance.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_update_insurance(client, user, vehicle):
    i = create_insurance(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:insurance_update", args=[vehicle.pk, i.pk]),
        insurance_form_post_data(
            vehicle,
            insurance_type="kasko",
            company="Ингосстрах",
            policy_number="КАСК 0023456789",
            cost="30000.00",
            reminder_created="",
        ),
    )
    assert response.status_code == 302
    i.refresh_from_db()
    assert i.insurance_type == "kasko"
    assert i.company == "Ингосстрах"
    assert i.cost == Decimal("30000.00")
    assert i.reminder_created is False


@pytest.mark.django_db
def test_soft_delete_insurance(client, user, vehicle):
    i = create_insurance(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:insurance_delete", args=[vehicle.pk, i.pk]))
    assert response.status_code == 302
    i.refresh_from_db()
    assert i.is_deleted is True
    assert not Insurance.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_insurance_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    other_vehicle = Vehicle.objects.create(user=other)
    i = create_insurance(vehicle)
    client.force_login(other)
    assert (
        client.get(reverse("vehicles:insurance_create", args=[vehicle.pk])).status_code
        == 404
    )
    assert (
        client.get(
            reverse("vehicles:insurance_update", args=[vehicle.pk, i.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("vehicles:insurance_delete", args=[vehicle.pk, i.pk])
        ).status_code
        == 404
    )
    assert Insurance.objects.get(pk=i.pk).is_deleted is False
    assert (
        client.get(reverse("vehicles:insurance_create", args=[other_vehicle.pk])).status_code
        == 200
    )


@pytest.mark.django_db
def test_insurance_summary_service(vehicle, user):
    from datetime import date, timedelta

    from apps.vehicles import services

    today = date.today()
    create_insurance(vehicle, cost=Decimal("8500.00"), end_date=today + timedelta(days=10))
    create_insurance(vehicle, cost=Decimal("30000.00"), end_date=today + timedelta(days=365))
    create_insurance(vehicle, cost=Decimal("5000.00"), end_date=today - timedelta(days=1))
    summary = services.insurance_summary(vehicle.pk)
    assert summary["count"] == 3
    assert summary["active"] == 2
    assert summary["expired"] == 1
    assert summary["expiring"] == 1
    assert summary["yearly"] == Decimal("38500.00")