# -*- coding: utf-8 -*-
"""Тесты 2FA-бэкенда (Этап 7.1): сервис, challenge middleware, шаг входа."""

import pytest
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from django.urls import reverse

from apps.accounts import twofactor
from apps.accounts.models import User


def _token(device, drift=0):
    """TOTP-код устройства. drift=1 — следующее 30-сек окно (валидный код уже был израсходован)."""
    return str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=drift))


@pytest.fixture
def no_throttle(settings):
    """Экспоненциальный backoff django-otp ломает сценарии «неверный код → верный» в тестах."""
    settings.OTP_TOTP_THROTTLE_FACTOR = 0
    settings.OTP_STATIC_THROTTLE_FACTOR = 0


def _enable(user):
    device = twofactor.begin_enable(user)
    assert twofactor.confirm_device(device, _token(device))
    return device


@pytest.fixture
def user(db):
    return User.objects.create_user(email="otp@test.ru", password="pass-12345")


class TestService:
    def test_begin_enable_creates_unconfirmed(self, user):
        device = twofactor.begin_enable(user)
        assert device.confirmed is False
        assert twofactor.get_device(user) is None
        assert twofactor.is_enabled(user) is False

    def test_begin_enable_resets_previous_draft(self, user):
        twofactor.begin_enable(user, name="old-draft")
        twofactor.begin_enable(user)
        assert TOTPDevice.objects.filter(user=user).count() == 1
        assert not TOTPDevice.objects.filter(user=user, name="old-draft").exists()

    def test_provisioning_secret_and_qr(self, user):
        device = twofactor.begin_enable(user)
        secret = twofactor.provisioning_secret(device)
        # base32 секрета достаточно длины и состоит из допустимых символов
        assert set(secret.replace("=", "")) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        assert len(secret.replace("=", "")) >= 26
        assert device.config_url.startswith("otpauth://totp/")
        qr = twofactor.provisioning_qr(device)
        assert "<svg" in qr and "qr-path" in qr

    def test_confirm_with_valid_and_invalid_token(self, user, no_throttle):
        device = twofactor.begin_enable(user)
        assert twofactor.confirm_device(device, "999999") is False
        assert twofactor.confirm_device(device, _token(device)) is True
        assert twofactor.is_enabled(user) is True

    def test_confirm_already_confirmed_device(self, user):
        device = twofactor.begin_enable(user)
        device.confirmed = True
        device.save()

        assert twofactor.confirm_device(device, "invalid") is True

    def test_totp_token_single_use(self, user, no_throttle):
        device = twofactor.begin_enable(user)
        tok0 = _token(device)
        assert twofactor.confirm_device(device, tok0) is True  # расходует окно
        assert twofactor.verify_any_token(user, tok0) is None  # replay того же токена
        # свежий код из следующего временного окна проходит
        assert twofactor.verify_any_token(user, _token(device, drift=1)) is not None

    def test_backup_codes_generation_and_single_use(self, user):
        _enable(user)
        codes = twofactor.generate_backup_codes(user)
        assert len(codes) == 10
        assert len(set(codes)) == 10
        assert twofactor.backup_codes_left(user) == 10
        device = twofactor.verify_any_token(user, codes[0])
        assert isinstance(device, StaticDevice)
        assert twofactor.backup_codes_left(user) == 9
        assert twofactor.verify_any_token(user, codes[0]) is None

    def test_backup_codes_confirm_existing_unconfirmed_device(self, user):
        draft = StaticDevice.objects.create(user=user, name="backup", confirmed=False)

        codes = twofactor.generate_backup_codes(user, count=1)

        draft.refresh_from_db()
        assert draft.confirmed is True
        assert draft.token_set.count() == 1
        assert len(codes) == 1

    def test_backup_codes_regenerate_invalidates_old(self, user, no_throttle):
        _enable(user)
        old = twofactor.generate_backup_codes(user)
        new = twofactor.generate_backup_codes(user)
        assert set(old) != set(new)
        assert twofactor.verify_any_token(user, old[0]) is None
        assert twofactor.verify_any_token(user, new[0]) is not None

    def test_disable_removes_all_devices(self, user):
        _enable(user)
        twofactor.generate_backup_codes(user)
        twofactor.disable(user)
        assert TOTPDevice.objects.filter(user=user).count() == 0
        assert StaticDevice.objects.filter(user=user).count() == 0
        assert twofactor.is_enabled(user) is False


@pytest.mark.django_db
class TestLoginChallenge:
    def test_verified_without_device_passes_through(self, client, user):
        client.force_login(user)
        assert client.get("/dashboard/").status_code == 200

    def test_2fa_user_gets_redirected_to_verify(self, client, user):
        _enable(user)
        client.force_login(user)
        response = client.get("/dashboard/")
        assert response.status_code == 302
        assert response.url.startswith(reverse("2fa:verify"))
        assert "next=/dashboard/" in response.url

    def test_challenge_page_and_success(self, client, user):
        _enable(user)
        client.force_login(user)
        verify_url = reverse("2fa:verify")
        assert client.get(verify_url).status_code == 200
        device = twofactor.get_device(user)
        response = client.post(verify_url, {"token": _token(device, drift=1), "next": "/dashboard/"})
        assert response.status_code == 302
        assert response.url == "/dashboard/"
        assert client.get("/dashboard/").status_code == 200

    def test_challenge_wrong_code_rejected_then_success(self, client, user, no_throttle):
        _enable(user)
        client.force_login(user)
        verify_url = reverse("2fa:verify")
        response = client.post(verify_url, {"token": "000111", "next": "/dashboard/"})
        assert response.status_code == 200
        device = twofactor.get_device(user)
        ok = client.post(verify_url, {"token": _token(device, drift=1), "next": "/dashboard/"})
        assert ok.status_code == 302

    def test_backup_code_passes_challenge(self, client, user):
        _enable(user)
        codes = twofactor.generate_backup_codes(user)
        client.force_login(user)
        verify_url = reverse("2fa:verify")
        response = client.post(verify_url, {"token": codes[0], "next": "/dashboard/"})
        assert response.status_code == 302
        assert twofactor.backup_codes_left(user) == 9

    def test_next_open_redirect_falls_back_to_dashboard(self, client, user):
        _enable(user)
        client.force_login(user)
        device = twofactor.get_device(user)
        response = client.post(
            reverse("2fa:verify"), {"token": _token(device, drift=1), "next": "http://evil.example/x"}
        )
        assert response.status_code == 302
        assert response.url == "/dashboard/"

    def test_verify_page_without_device_shows_not_enabled(self, client, user):
        client.force_login(user)
        response = client.get(reverse("2fa:verify"))
        assert response.status_code == 200
        assert "disabled" in response.context or "не включена" in response.content.decode("utf-8")

    def test_anonymous_goes_to_login_not_challenge(self, client):
        response = client.get("/dashboard/")
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_exempt_paths_for_2fa_user(self, client, user):
        _enable(user)
        client.force_login(user)
        assert client.get("/2fa/verify/").status_code == 200
        assert client.get("/logout/").status_code == 200
