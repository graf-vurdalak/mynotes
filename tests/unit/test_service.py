# -*- coding: utf-8 -*-
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.vehicles.models import Service, ServicePhoto, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="user@test.ru", password="pass12345")


@pytest.fixture
def vehicle(db, user):
    return Vehicle.objects.create(user=user, current_mileage=150000, is_default=True)


def make_png(name="photo.png", size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(
        name, buf.read(), content_type="image/png"
    )


def create_service(vehicle, **kwargs):
    data = dict(
        user=vehicle.user,
        vehicle=vehicle,
        service_station="АвтоСервис",
        work_description="ТО-60000 км",
        amount=Decimal("18500.00"),
        service_date="2026-07-12",
        odometer=154100,
        order_document="АБ-1234",
    )
    data.update(kwargs)
    return Service.objects.create(**data)


def service_form_post_data(vehicle, **overrides):
    data = dict(
        vehicle=vehicle.pk,
        service_date="2026-08-01",
        service_station="АвтоМастер",
        work_description="Замена масла",
        amount="4200.00",
        odometer="155000",
        order_document="ЗН-0001",
    )
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_service_tab_shows_entry(client, user, vehicle):
    s = create_service(vehicle)
    ServicePhoto.objects.create(service=s, image=make_png())
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert s.work_description in content
    assert s.service_station in content
    assert "18500" in content
    assert "1 фото" in content


@pytest.mark.django_db
def test_create_service(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle),
        format="multipart",
    )
    assert response.status_code == 302
    s = Service.objects.get(vehicle=vehicle)
    assert s.work_description == "Замена масла"
    assert s.service_station == "АвтоМастер"
    assert s.amount == Decimal("4200.00")
    assert s.odometer == 155000
    assert s.order_document == "ЗН-0001"
    assert s.user == user


@pytest.mark.django_db
def test_create_service_with_photos(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, photos=[make_png("a.png"), make_png("b.png")]),
        format="multipart",
    )
    assert response.status_code == 302
    s = Service.objects.get(vehicle=vehicle)
    assert s.photos.count() == 2
    assert list(s.photos.values_list("sort_order", flat=True)) == [1, 2]


@pytest.mark.django_db
def test_create_service_negative_amount(client, user, vehicle):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, amount="-100"),
        format="multipart",
    )
    assert response.status_code == 200
    assert "Стоимость" in response.content.decode("utf-8")
    assert not Service.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_service_invalid_mime_rejected(client, user, vehicle):
    bad = SimpleUploadedFile("doc.txt", b"not-an-image", content_type="text/plain")
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, photos=[bad]),
        format="multipart",
    )
    assert response.status_code == 200
    assert "недопустимый формат" in response.content.decode("utf-8")
    assert not Service.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_service_spoofed_content_type_rejected(client, user, vehicle):
    spoofed = SimpleUploadedFile(
        "evil.png", b"<script>alert(1)</script>", content_type="image/png"
    )
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, photos=[spoofed]),
        format="multipart",
    )
    assert response.status_code == 200
    assert "недопустимый формат" in response.content.decode("utf-8")
    assert not Service.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_service_too_many_photos_rejected(client, user, vehicle):
    photos = [make_png(f"p{i}.png") for i in range(11)]
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, photos=photos),
        format="multipart",
    )
    assert response.status_code == 200
    assert "не более 10" in response.content.decode("utf-8")
    assert not Service.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_create_service_oversized_photo_rejected(client, user, vehicle):
    big = SimpleUploadedFile(
        "big.png",
        b"\x00" * (10 * 1024 * 1024 + 1),
        content_type="image/png",
    )
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_create", args=[vehicle.pk]),
        service_form_post_data(vehicle, photos=[big]),
        format="multipart",
    )
    assert response.status_code == 200
    assert "больше 10 МБ" in response.content.decode("utf-8")
    assert not Service.objects.filter(vehicle=vehicle).exists()


@pytest.mark.django_db
def test_update_service(client, user, vehicle):
    s = create_service(vehicle)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_update", args=[vehicle.pk, s.pk]),
        service_form_post_data(
            vehicle,
            work_description="Замена колодок",
            amount="6200.00",
            odometer="149800",
            order_document="",
        ),
        format="multipart",
    )
    assert response.status_code == 302
    s.refresh_from_db()
    assert s.work_description == "Замена колодок"
    assert s.amount == Decimal("6200.00")
    assert s.odometer == 149800
    assert s.order_document == ""


@pytest.mark.django_db
def test_update_service_adds_photos_without_removing_old(client, user, vehicle):
    s = create_service(vehicle)
    ServicePhoto.objects.create(service=s, image=make_png("old.png"), sort_order=1)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_update", args=[vehicle.pk, s.pk]),
        service_form_post_data(vehicle, photos=[make_png("new.png")]),
        format="multipart",
    )
    assert response.status_code == 302
    s.refresh_from_db()
    assert s.photos.count() == 2


@pytest.mark.django_db
def test_update_service_cap_includes_existing_photos(client, user, vehicle):
    s = create_service(vehicle)
    ServicePhoto.objects.create(service=s, image=make_png("p1.png"), sort_order=1)
    ServicePhoto.objects.create(service=s, image=make_png("p2.png"), sort_order=2)
    client.force_login(user)
    response = client.post(
        reverse("vehicles:service_update", args=[vehicle.pk, s.pk]),
        service_form_post_data(vehicle, photos=[make_png(f"n{i}.png") for i in range(9)]),
        format="multipart",
    )
    assert response.status_code == 200
    assert "не более 10" in response.content.decode("utf-8")
    s.refresh_from_db()
    assert s.photos.count() == 2


@pytest.mark.django_db
def test_soft_delete_service(client, user, vehicle):
    s = create_service(vehicle)
    client.force_login(user)
    response = client.post(reverse("vehicles:service_delete", args=[vehicle.pk, s.pk]))
    assert response.status_code == 302
    s.refresh_from_db()
    assert s.is_deleted is True
    assert not Service.objects.filter(vehicle=vehicle, is_deleted=False).exists()


@pytest.mark.django_db
def test_service_idor(client, user, vehicle):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    other_vehicle = Vehicle.objects.create(user=other)
    s = create_service(vehicle)
    client.force_login(other)
    assert (
        client.get(reverse("vehicles:service_create", args=[vehicle.pk])).status_code
        == 404
    )
    assert (
        client.get(reverse("vehicles:service_update", args=[vehicle.pk, s.pk])).status_code
        == 404
    )
    assert (
        client.post(reverse("vehicles:service_delete", args=[vehicle.pk, s.pk])).status_code
        == 404
    )
    assert Service.objects.get(pk=s.pk).is_deleted is False
    assert (
        client.get(reverse("vehicles:service_create", args=[other_vehicle.pk])).status_code
        == 200
    )


@pytest.mark.django_db
def test_service_summary_service(vehicle, user):
    from apps.vehicles import services

    create_service(vehicle, amount=Decimal("18500.00"), service_date="2026-07-12")
    create_service(vehicle, amount=Decimal("6200.00"), service_date="2025-06-28")
    summary = services.service_summary(vehicle.pk, year=2026)
    assert summary["count"] == 1
    assert summary["total"] == Decimal("18500.00")
    assert len(summary["items"]) == 1
