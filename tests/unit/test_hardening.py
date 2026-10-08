# -*- coding: utf-8 -*-
"""Этап 7.6: hardening безопасности (ТЗ 8.1–8.6)."""

import secrets

import pytest
from django.db import connection
from django.urls import reverse

from apps.accounts.forms import SignupForm
from apps.accounts.models import User
from apps.core.crypto import decrypt_value
from apps.vehicles.models import Vehicle

VALID_VIN = "XW7BF4FK50S123456"


@pytest.fixture
def user(db):
    return User.objects.create_user(email="harden@test.ru", password="Str0ng!Passw0rd")


@pytest.mark.django_db
def test_argon2_is_default_hasher():
    from django.conf import settings

    assert settings.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    user = User.objects.create_user(email="hash@test.ru", password="SomePassw0rd!")
    assert user.password.startswith("argon2")


@pytest.mark.django_db
def test_signup_password_validators_min10():
    base = {"email": "new@test.ru", "display_name": ""}
    assert not SignupForm(data={**base, "password": "short123"}).is_valid()
    assert not SignupForm(data={**base, "password": "password123"}).is_valid()  # common
    assert not SignupForm(data={**base, "password": "1234567890"}).is_valid()  # numeric-only
    assert not SignupForm(data={**base, "password": "notavalue"}).is_valid()  # 9 < min 10
    assert SignupForm(data={**base, "password": "Xk9!mQ2vLp7r"}).is_valid()


@pytest.mark.django_db
def test_login_rate_limited_429(client, settings):
    settings.RATELIMIT_LOGIN = "2/m"
    url = reverse("login")
    remote = f"10.60.{secrets.randbelow(200) + 1}.{secrets.randbelow(250) + 1}"
    body = {"email": "nope@test.ru", "password": "Whatever123!"}
    for _ in range(2):
        assert client.post(url, body, REMOTE_ADDR=remote).status_code == 200
    response = client.post(url, body, REMOTE_ADDR=remote)
    assert response.status_code == 429
    assert "429" in response.content.decode("utf-8") or "Слишком" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_login_get_not_counted(client, settings):
    settings.RATELIMIT_LOGIN = "1/m"
    url = reverse("login")
    remote = f"10.61.{secrets.randbelow(200) + 1}.{secrets.randbelow(250) + 1}"
    for _ in range(5):
        assert client.get(url, REMOTE_ADDR=remote).status_code == 200


@pytest.mark.django_db
def test_signup_rate_limited_429(client, settings):
    settings.RATELIMIT_SIGNUP = "1/m"
    url = reverse("accounts:signup")
    remote = f"10.62.{secrets.randbelow(200) + 1}.{secrets.randbelow(250) + 1}"
    assert client.post(url, {}, REMOTE_ADDR=remote).status_code == 200  # ошибки формы, счётчик уже +1
    assert client.post(url, {}, REMOTE_ADDR=remote).status_code == 429


@pytest.mark.django_db
def test_csp_header_allows_project_cdns(client):
    response = client.get(reverse("login"))
    header = response["Content-Security-Policy"]
    assert "default-src 'self'" in header
    assert "https://cdn.tailwindcss.com" in header
    assert "https://cdn.jsdelivr.net" in header
    assert "https://unpkg.com" in header
    assert "object-src 'none'" in header
    assert "frame-ancestors 'none'" in header


@pytest.mark.django_db
def test_vin_encrypted_at_rest(user):
    vehicle = Vehicle.objects.create(user=user, vin=VALID_VIN, brand_custom="Тест")
    with connection.cursor() as cursor:
        cursor.execute("SELECT vin FROM vehicle_vehicle WHERE id = %s", [vehicle.pk])
        stored = cursor.fetchone()[0]
    assert stored != VALID_VIN
    assert decrypt_value(stored) == VALID_VIN
    assert Vehicle.objects.get(pk=vehicle.pk).vin == VALID_VIN


@pytest.mark.django_db
def test_vin_blank_stays_blank(user):
    vehicle = Vehicle.objects.create(user=user, vin="", brand_custom="Без VIN")
    with connection.cursor() as cursor:
        cursor.execute("SELECT vin FROM vehicle_vehicle WHERE id = %s", [vehicle.pk])
        assert cursor.fetchone()[0] == ""


@pytest.mark.django_db
def test_vin_legacy_plaintext_readable(user):
    # Данные до шифрования (миграция 0009) должны читаться до перешифровки.
    vehicle = Vehicle.objects.create(user=user, vin=VALID_VIN, brand_custom="Легаси")
    with connection.cursor() as cursor:
        cursor.execute("UPDATE vehicle_vehicle SET vin = %s WHERE id = %s", [VALID_VIN, vehicle.pk])
    assert Vehicle.objects.get(pk=vehicle.pk).vin == VALID_VIN


def test_done_items_checklist():
    """Верификация ранее выполненных пунктов ТЗ 8 (чек-верификация 7.6)."""
    from django.conf import settings

    # 8.2: Redis-сессии, TTL 7 дней
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.cached_db"
    assert settings.SESSION_CACHE_ALIAS == "default"
    assert settings.SESSION_COOKIE_AGE == 604800

    # 8.4: CORS не открыт на весь мир; rate-limit настройки заданы
    assert not getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)
    assert settings.RATELIMIT_API and settings.RATELIMIT_LOGIN and settings.RATELIMIT_SIGNUP

    # 8.4: HTTPS/HSTS/secure cookies в проде; 8.6: секреты только из env
    import config.settings.prod as prod

    assert prod.DEBUG is False
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_HSTS_SECONDS >= 31536000


# ---------------------------------------------------------------------------
# Фиксы ревью Этапа 7 (регрессии)
# ---------------------------------------------------------------------------


def test_client_ip_trusts_rightmost_xff_hop():
    """Ревью №1: nginx дописывает реальный IP справа — левый элемент спуфится."""
    from django.test import RequestFactory

    from apps.accounts.audit import client_ip

    req = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.1.1.1, 9.9.9.9", REMOTE_ADDR="127.0.0.1"
    )
    assert client_ip(req) == "9.9.9.9"


def test_client_ip_falls_back_on_garbage():
    from django.test import RequestFactory

    from apps.accounts.audit import client_ip

    req = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="evil, not-an-ip", REMOTE_ADDR="127.0.0.1"
    )
    assert client_ip(req) == "127.0.0.1"


@pytest.mark.django_db
def test_login_with_garbage_xff_records_fallback_ip(client, user):
    """Мусорный XFF не должен ронять запись журнала (inet-колонка)."""
    response = client.post(
        "/login/",
        {"email": "harden@test.ru", "password": "Str0ng!Passw0rd"},
        REMOTE_ADDR="10.77.1.1",
        headers={"X-Forwarded-For": "garbage-value"},
    )
    assert response.status_code == 302
    from apps.accounts.models import AuthSessionLog

    log = AuthSessionLog.objects.get(user=user)
    assert log.ip_address == "10.77.1.1"


@pytest.mark.django_db
def test_provider_account_backend_is_email(user):
    """Ревью №9: автологин подтверждения email (allauth account-backend) ≠ social."""
    from apps.accounts.signals import _provider_for

    user.backend = "allauth.account.auth_backends.AuthenticationBackend"
    assert _provider_for(user) == "email"

    from allauth.socialaccount.models import SocialAccount

    SocialAccount.objects.create(user=user, provider="yandex", uid="42")
    user.backend = "allauth.socialaccount.providers.yandex.provider"
    assert _provider_for(user) == "yandex"


@pytest.mark.django_db
def test_signup_email_conflict_is_case_insensitive(db):
    """Ревью №7: mixed-case строки (social-созданные) ловятся signup."""
    from apps.accounts.forms import SignupForm

    User.objects.create_user(email="Case@Test.local", password="Whatever123!")
    form = SignupForm(data={"email": "case@test.local", "password": "Str0ng!Passw0rd", "display_name": ""})
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_issued_token_original_not_persisted_in_session(client, user):
    """Ревью №3: оригинал токена — только Redis-кэш (TTL) и один показ; в
    django_session (write-through в Postgres) plaintext попадать не должен."""
    from django.contrib.sessions.models import Session
    from django.core.cache import cache

    from apps.accounts.models import AuthToken

    client.force_login(user)
    response = client.post(reverse("accounts:tokens"), {"name": "smoke783"})
    assert response.status_code == 302
    tok = AuthToken.objects.get(user=user, name="smoke783")
    plain = cache.get(f"onetime:token:{tok.pk}")
    assert plain

    page = client.get(response.url)
    assert page.status_code == 200
    assert plain in page.content.decode()
    assert cache.get(f"onetime:token:{tok.pk}") is None  # одноразовость

    session = Session.objects.get(session_key=client.session.session_key)
    assert plain not in str(session.get_decoded())



@pytest.mark.django_db
def test_existing_session_challenged_after_late_2fa_enable(client, user):
    """Ревью №2: устройство, включённое после входа, обязано потребовать challenge."""
    from django_otp.oath import totp

    from apps.accounts import twofactor

    client.force_login(user)
    assert client.get("/dashboard/").status_code == 200

    device = twofactor.begin_enable(user)
    code = str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits))
    assert twofactor.confirm_device(device, code)

    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert "2fa/verify" in response.url


@pytest.mark.django_db
def test_timezone_not_leaked_between_requests(client, user, db, settings):
    """Ревью №8: аноним/пользователь без настроек не наследует пояс прошлого запроса."""
    from django.utils import timezone as dj_tz

    from apps.accounts.models import UserSettings

    UserSettings.objects.update_or_create(user=user, defaults={"timezone": "Europe/Berlin"})
    client.force_login(user)
    assert client.get("/dashboard/").status_code == 200
    assert dj_tz.get_current_timezone_name() == "Europe/Berlin"

    client.logout()
    anon = client.get("/")  # login-редирект, но middleware уже отработал
    assert dj_tz.get_current_timezone_name() == settings.TIME_ZONE
    assert anon.status_code in (200, 302)


def test_vin_migration_refuses_prod_without_fernet_key(settings):
    """Ревью №4: в не-DEBUG без FERNET_KEY миграция 0009 обязана остановиться."""
    import importlib

    m = importlib.import_module("apps.vehicles.migrations.0009_encrypt_vehicle_vin")
    settings.DEBUG = False
    settings.FERNET_KEY = ""
    with pytest.raises(RuntimeError):
        m._require_key()
    settings.FERNET_KEY = "some-key"
    m._require_key()  # не бросает
    settings.DEBUG = True
    settings.FERNET_KEY = ""
    m._require_key()  # dev без ключа — легально (производный от SECRET_KEY)

