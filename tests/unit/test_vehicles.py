# -*- coding: utf-8 -*-
import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.references.models import CarBrand, CarModel
from apps.vehicles.models import Vehicle


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
        year=2021,
        vin="XW7BF4FK50S123456",
        license_plate="А777АА 77",
        fuel_type="petrol",
        engine_volume="2.5",
        power_hp=200,
        transmission="at",
        drive_type="fwd",
        current_mileage=156420,
        is_default=True,
    )


@pytest.mark.django_db
def test_list_requires_login(client):
    response = client.get(reverse("vehicles:list"))
    assert response.status_code == 302
    assert "/login/" in response.url


@pytest.mark.django_db
def test_list_empty(client, user):
    client.force_login(user)
    response = client.get(reverse("vehicles:list"))
    assert response.status_code == 200
    assert "Мой автопарк" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_list_shows_vehicle(client, user, vehicle):
    client.force_login(user)
    response = client.get(reverse("vehicles:list"))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Toyota" in content
    assert "А777АА 77" in content
    assert "156420" in content


@pytest.mark.django_db
def test_create_vehicle(client, user, brand, car_model):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:create"),
        {
            "brand": brand.id,
            "brand_custom": "",
            "model": car_model.id,
            "model_custom": "",
            "year": "2022",
            "vin": "XW7BF4FK50S123457",
            "license_plate": "В456ВВ 199",
            "fuel_type": "diesel",
            "engine_volume": "2.0",
            "power_hp": "150",
            "transmission": "mt",
            "drive_type": "fwd",
            "current_mileage": "1000",
            "is_default": "on",
        },
    )
    assert response.status_code == 302
    v = Vehicle.objects.get(user=user)  # равенство по vin невозможно: поле шифруется (ТЗ 8.5)
    assert v.vin == "XW7BF4FK50S123457"
    assert v.brand == brand
    assert v.model == car_model
    assert v.engine_volume == 2.0
    assert v.is_default is True
    assert v.fuel_type == "diesel"


@pytest.mark.django_db
def test_first_vehicle_becomes_default(client, user, brand, car_model):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:create"),
        {
            "brand": brand.id,
            "model": car_model.id,
            "year": "2020",
            "vin": "XW7BF4FK50S123458",
        },
    )
    assert response.status_code == 302
    assert Vehicle.objects.get(user=user).is_default is True


@pytest.mark.django_db
def test_vine_length_validation(client, user, brand):
    client.force_login(user)
    response = client.post(
        reverse("vehicles:create"),
        {"brand": brand.id, "vin": "SHORT"},
    )
    assert response.status_code == 200
    assert "17 символов" in response.content.decode("utf-8")
    assert not Vehicle.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_update_vehicle(client, user, vehicle):
    client.force_login(user)
    url = reverse("vehicles:update", args=[vehicle.pk])
    response = client.post(
        url,
        {
            "brand": "",
            "brand_custom": "Lada",
            "model": "",
            "model_custom": "Vesta",
            "year": "2023",
            "vin": "XW7BF4FK50S123456",
            "license_plate": "А001АА 77",
            "fuel_type": "petrol",
            "power_hp": "120",
            "transmission": "mt",
            "drive_type": "fwd",
        },
    )
    assert response.status_code == 302
    vehicle.refresh_from_db()
    assert vehicle.brand_custom == "Lada"
    assert vehicle.model_custom == "Vesta"
    assert vehicle.brand is None
    assert vehicle.license_plate == "А001АА 77"


@pytest.mark.django_db
def test_soft_delete_vehicle(client, user, vehicle):
    client.force_login(user)
    response = client.post(reverse("vehicles:delete", args=[vehicle.pk]))
    assert response.status_code == 302
    vehicle.refresh_from_db()
    assert vehicle.is_deleted is True
    assert not Vehicle.objects.filter(user=user, is_deleted=False).exists()


@pytest.mark.django_db
def test_set_default(client, user, brand, car_model, vehicle):
    other = Vehicle.objects.create(
        user=user, brand=brand, model=car_model, is_default=False
    )
    client.force_login(user)
    response = client.post(reverse("vehicles:set_default", args=[other.pk]))
    assert response.status_code == 302
    other.refresh_from_db()
    vehicle.refresh_from_db()
    assert other.is_default is True
    assert vehicle.is_default is False


@pytest.mark.django_db
def test_idor_list_isolated(client, user, vehicle):
    other_user = User.objects.create_user(
        email="other@test.ru", password="pass12345"
    )
    client.force_login(other_user)
    response = client.get(reverse("vehicles:list"))
    assert response.status_code == 200
    assert vehicle.license_plate not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_detail_requires_login(client, vehicle):
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    assert response.status_code == 302
    assert "/login/" in response.url


@pytest.mark.django_db
def test_detail_shows_vehicle(client, user, vehicle):
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Toyota" in content
    assert "А777АА 77" in content
    assert "Бортжурнал" in content
    assert "Статистика" in content
    assert "Заправки" in content


@pytest.mark.django_db
def test_detail_idor_isolated(client, user, vehicle):
    other_user = User.objects.create_user(
        email="other@test.ru", password="pass12345"
    )
    client.force_login(other_user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_detail_deleted_returns_404(client, user, vehicle):
    vehicle.delete()
    client.force_login(user)
    response = client.get(reverse("vehicles:detail", args=[vehicle.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_models_api(client, user, brand, car_model):
    client.force_login(user)
    response = client.get(reverse("vehicles:models_api"), {"brand": brand.id})
    assert response.status_code == 200
    data = response.json()["models"]
    assert any(m["name"] == "Camry" for m in data)
