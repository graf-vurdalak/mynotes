# -*- coding: utf-8 -*-
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.vehicles.models import Fine, Purchase, PurchaseCategory, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


@pytest.fixture
def fines_category(db):
    return PurchaseCategory.objects.create(
        name="Штрафы", color="#8B5CF6", is_system=True, sort_order=5
    )


def make_png(name="fine.png", size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def create_fine(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        fine_date="2026-07-05",
        decision_number="18810177200718000123",
        article="12.9",
        description="Превышение скорости на 40 км/ч",
        amount=Decimal("2500.00"),
        status="unpaid",
    )
    data.update(kwargs)
    return Fine.objects.create(**data)


def fine_form_post_data(vehicle, **overrides):
    data = dict(
        vehicle=vehicle.pk,
        fine_date="2026-08-01",
        decision_number="18810177200718000123",
        article="12.9",
        amount="2500.00",
        status="unpaid",
        paid_at="",
        description="Превышение скорости",
    )
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_fine_tab_shows_entry(client, user, vehicle):
    f = create_fine(vehicle)
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert f.description in content
    assert "18810177200718000123" in content
    assert "2500" in content


@pytest.mark.django_db
def test_fine_tab_filters_by_status(client, user, vehicle):
    create_fine(vehicle, description="Неоплаченный", status="unpaid")
    create_fine(vehicle, description="Оплаченный", status="paid", paid_at="2026-07-10")
    client.force_login(user)
    response = client.get(
        reverse("vehicles:detail", args=[vehicle.pk]), {"fine_status": "paid"}
    )
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Оплаченный" in content
    assert "Неоплаченный" not in content


@pytest.mark.django_db
def test_create_fine(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle),
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.decision_number == "18810177200718000123"
    assert f.article == "12.9"
    assert f.amount == Decimal("2500.00")
    assert f.status == "unpaid"
    assert f.description == "Превышение скорости"
    assert f.user == user
    assert f.paid_at is None


@pytest.mark.django_db
def test_create_fine_paid_autofills_paid_at(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, status="paid"),
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.status == "paid"
    assert f.paid_at.isoformat() == "2026-08-01"


@pytest.mark.django_db
def test_create_fine_invalid_uin_rejected(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, decision_number="123"),
    )
    assert response.status_code == 200
    assert "УИН должен содержать от 20 до 25 цифр" in response.content.decode("utf-8")
    assert not Fine.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_fine_negative_amount_rejected(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, amount="-100"),
    )
    assert response.status_code == 200
    assert "Сумма" in response.content.decode("utf-8")
    assert not Fine.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_fine_with_photo(client, user, vehicle):
    data = fine_form_post_data(vehicle)
    data["photo"] = make_png()
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        data,
        format="multipart",
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.photo.name.endswith(".png")


@pytest.mark.django_db
def test_create_fine_spoofed_photo_rejected(client, user, vehicle):
    data = fine_form_post_data(vehicle)
    data["photo"] = SimpleUploadedFile(
        "evil.png", b"<script>alert(1)</script>", content_type="image/png"
    )
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        data,
        format="multipart",
    )
    assert response.status_code == 200
    assert not Fine.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_fine_links_purchase_when_paid(
    client, user, vehicle, fines_category
):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, status="paid", link_purchase="on"),
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.purchase is not None
    p = f.purchase
    assert p.category == fines_category
    assert p.amount == Decimal("2500.00")
    assert p.user == user
    assert p.vehicle == vehicle
    assert p.title == "Превышение скорости"


@pytest.mark.django_db
def test_create_fine_unpaid_no_purchase(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, link_purchase="on"),
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.purchase is None
    assert not Purchase.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_update_fine(client, user, vehicle):
    f = create_fine(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_update", args=[vehicle.pk, f.pk]),
        fine_form_post_data(
            vehicle,
            decision_number="18810177180601000456",
            article="12.12",
            amount="1000.00",
            status="paid",
            description="Проезд на запрещающий сигнал",
        ),
    )
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.decision_number == "18810177180601000456"
    assert f.amount == Decimal("1000.00")
    assert f.status == "paid"
    assert f.paid_at.isoformat() == "2026-08-01"
    assert f.description == "Проезд на запрещающий сигнал"


@pytest.mark.django_db
def test_soft_delete_fine(client, user, vehicle):
    f = create_fine(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:fine_delete", args=[vehicle.pk, f.pk]))
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.is_deleted is True
    assert not Fine.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_fine_status_change(client, user, vehicle):
    f = create_fine(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_status", args=[vehicle.pk, f.pk]), {"status": "paid"}
    )
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.status == "paid"
    assert f.paid_at is not None


@pytest.mark.django_db
def test_fine_status_change_clears_paid_at(client, user, vehicle):
    f = create_fine(vehicle, status="paid", paid_at="2026-07-10")
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_status", args=[vehicle.pk, f.pk]), {"status": "unpaid"}
    )
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.status == "unpaid"
    assert f.paid_at is None


@pytest.mark.django_db
def test_unlink_purchase_removes_expense(client, user, vehicle, fines_category):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_create", args=[vehicle.pk]),
        fine_form_post_data(vehicle, status="paid", link_purchase="on"),
    )
    assert response.status_code == 302
    f = Fine.objects.get(vehicle=vehicle)
    assert f.purchase is not None
    purchase = f.purchase

    response = client.post(
        reverse("vehicles:fine_update", args=[vehicle.pk, f.pk]),
        fine_form_post_data(vehicle, status="unpaid", link_purchase="on"),
    )
    assert response.status_code == 302
    f.refresh_from_db()
    purchase.refresh_from_db()
    assert f.purchase is None
    assert purchase.is_deleted is True
    assert not Purchase.objects.filter(
        vehicle=vehicle, is_deleted=False, category=fines_category
    ).exists()


@pytest.mark.django_db
def test_fine_status_change_invalid_value(client, user, vehicle):
    f = create_fine(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:fine_status", args=[vehicle.pk, f.pk]), {"status": "bogus"}
    )
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.status == "unpaid"


@pytest.mark.django_db
def test_fine_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    other_vehicle = Vehicle.objects.create(user=other)
    f = create_fine(vehicle)
    client.force_login(other)
    assert (
        client.get(reverse("vehicles:fine_create", args=[vehicle.pk])).status_code
        == 404
    )
    assert (
        client.get(reverse("vehicles:fine_update", args=[vehicle.pk, f.pk])).status_code
        == 404
    )
    assert (
        client.post(reverse("vehicles:fine_delete", args=[vehicle.pk, f.pk])).status_code
        == 404
    )
    assert (
        client.post(
            reverse("vehicles:fine_status", args=[vehicle.pk, f.pk]), {"status": "paid"}
        ).status_code
        == 404
    )
    assert Fine.objects.get(pk=f.pk).is_deleted is False
    assert (
        client.get(reverse("vehicles:fine_create", args=[other_vehicle.pk])).status_code
        == 200
    )


@pytest.mark.django_db
def test_fine_summary_service(vehicle, user):
    from apps.vehicles import services

    create_fine(vehicle, amount=Decimal("2500.00"), status="unpaid")
    create_fine(vehicle, amount=Decimal("1000.00"), status="paid")
    summary = services.fine_summary(vehicle.pk)
    assert summary["count"] == 2
    assert summary["total"] == Decimal("3500.00")
    assert summary["unpaid"] == Decimal("2500.00")
    assert summary["paid"] == Decimal("1000.00")
