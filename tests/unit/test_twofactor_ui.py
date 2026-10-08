# -*- coding: utf-8 -*-
"""Тесты 2FA UI в ЛК (Этап 7.4): мастер включения, резервные коды, перегенерация, выключение."""

import re

import pytest
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from django.urls import reverse

from apps.accounts import twofactor
from apps.accounts.models import User


def _token(device, drift=0):
    return str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=drift))


def _enable_via_service(user):
    device = twofactor.begin_enable(user)
    assert twofactor.confirm_device(device, _token(device))
    return device


@pytest.fixture
def user(db):
    return User.objects.create_user(email="ui-2fa@test.ru", password="Passw0rd-123")


@pytest.fixture
def no_throttle(settings):
    settings.OTP_TOTP_THROTTLE_FACTOR = 0
    settings.OTP_STATIC_THROTTLE_FACTOR = 0


def _setup(client):
    response = client.post(reverse("accounts:twofa_setup"), {"action": "create"})
    assert response.status_code == 200
    return response


def _confirm(client):
    """Полный мастер: create + confirm; возвращает активированное устройство."""
    _setup(client)
    device = TOTPDevice.objects.filter(confirmed=False).first()
    response = client.post(reverse("accounts:twofa_setup"), {"action": "confirm", "token": _token(device)})
    assert response.status_code == 302
    return device


def _pass_challenge(client, device):
    """Сессия после force_login не верифицирована — проходим шаг 2FA."""
    response = client.post(reverse("2fa:verify"), {
        "token": _token(device, drift=1),
        "next": reverse("accounts:settings_security"),
    })
    assert response.status_code == 302
    return response


def _codes_in(page):
    return re.findall(r">([a-z2-7]{8})</div>", page)


@pytest.mark.django_db
class TestSetupWizard:
    def test_login_required(self, client, user):
        response = client.post(reverse("accounts:twofa_setup"), {"action": "create"})
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_get_without_pending_redirects(self, client, user):
        client.force_login(user)
        response = client.get(reverse("accounts:twofa_setup"))
        assert response.status_code == 302
        assert response.url == reverse("accounts:settings_security")

    def test_create_shows_qr_and_secret(self, client, user):
        client.force_login(user)
        page = _setup(client).content.decode("utf-8")
        assert "<svg" in page
        assert TOTPDevice.objects.filter(user=user, confirmed=False).count() == 1

    def test_confirm_wrong_code_keeps_pending(self, client, user, no_throttle):
        client.force_login(user)
        _setup(client)
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        response = client.post(reverse("accounts:twofa_setup"), {"action": "confirm", "token": "000000"})
        assert response.status_code == 200
        device.refresh_from_db()
        assert device.confirmed is False

    def test_confirm_success_and_backup_once(self, client, user):
        client.force_login(user)
        _setup(client)
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        response = client.post(reverse("accounts:twofa_setup"), {"action": "confirm", "token": _token(device)})
        assert response.status_code == 302
        assert response.url == reverse("accounts:twofa_backup")
        assert twofactor.is_enabled(user)

        page = client.get(reverse("accounts:twofa_backup")).content.decode("utf-8")
        codes = _codes_in(page)
        assert len(codes) == 10
        assert twofactor.backup_codes_left(user) == 10

        # повторный заход — коды уже не показываются
        again = client.get(reverse("accounts:twofa_backup"))
        assert again.status_code == 302

        # статус на странице безопасности
        sec = client.get(reverse("accounts:settings_security")).content.decode("utf-8")
        assert "Включена" in sec

    def test_enable_does_not_challenge_current_session(self, client, user):
        client.force_login(user)
        _confirm(client)
        assert client.get("/dashboard/").status_code == 200
        # на следующем входе middleware потребует код — флаг пересчитан в новой сессии
        client.logout()
        client.force_login(user)
        response = client.get("/dashboard/")
        assert response.status_code == 302
        assert response.url.startswith(reverse("2fa:verify"))

    def test_cancel_removes_draft(self, client, user):
        client.force_login(user)
        _setup(client)
        response = client.post(reverse("accounts:twofa_setup"), {"action": "cancel"})
        assert response.status_code == 302
        assert TOTPDevice.objects.filter(user=user).count() == 0

    def test_restart_resets_draft(self, client, user):
        client.force_login(user)
        _setup(client)
        _setup(client)
        assert TOTPDevice.objects.filter(user=user, confirmed=False).count() == 1


@pytest.mark.django_db
class TestBackupManagement:
    def test_regenerate_shows_new_codes(self, client, user):
        client.force_login(user)
        _confirm(client)
        old_backup = twofactor.backup_codes_left(user)
        response = client.post(reverse("accounts:twofa_regenerate"))
        assert response.status_code == 302
        assert response.url == reverse("accounts:twofa_backup")
        page = client.get(reverse("accounts:twofa_backup")).content.decode("utf-8")
        assert len(_codes_in(page)) == 10
        assert twofactor.backup_codes_left(user) == old_backup == 10

    def test_regenerate_requires_enabled(self, client, user):
        client.force_login(user)
        response = client.post(reverse("accounts:twofa_regenerate"))
        assert response.status_code == 302
        assert response.url == reverse("accounts:settings_security")
        assert StaticDevice.objects.filter(user=user).count() == 0


@pytest.mark.django_db
class TestDisable:
    def test_disable_requires_valid_code(self, client, user, no_throttle):
        client.force_login(user)
        device = _confirm(client)
        response = client.post(reverse("accounts:twofa_disable"), {"token": "000000"})
        assert response.status_code == 302
        assert twofactor.is_enabled(user) is True
        # валидный код из следующего окна (мастер израсходовал текущее)
        client.post(reverse("accounts:twofa_disable"), {"token": _token(device, drift=1)})
        assert twofactor.is_enabled(user) is False
        assert TOTPDevice.objects.filter(user=user).count() == 0

    def test_disable_passes_with_backup_code(self, client, user):
        client.force_login(user)
        _confirm(client)
        codes = twofactor.backup_codes_left(user)
        assert codes == 10
        new_list = None
        # достанем сами коды через перегенерацию (страница показывает их один раз)
        client.post(reverse("accounts:twofa_regenerate"))
        page = client.get(reverse("accounts:twofa_backup")).content.decode("utf-8")
        new_list = _codes_in(page)
        response = client.post(reverse("accounts:twofa_disable"), {"token": new_list[0]})
        assert response.status_code == 302
        assert twofactor.is_enabled(user) is False
        assert StaticDevice.objects.filter(user=user).count() == 0

    def test_after_disable_no_challenge(self, client, user):
        client.force_login(user)
        device = _confirm(client)
        client.post(reverse("accounts:twofa_disable"), {"token": _token(device, drift=1)})
        assert client.get("/dashboard/").status_code == 200
        client.logout()
        client.force_login(user)
        assert client.get("/dashboard/").status_code == 200

    def test_service_enabled_user_passes_challenge(self, client, user):
        """Включённый до входа пользователь обязан подтвердить код в новой сессии."""
        device = _enable_via_service(user)
        client.force_login(user)
        # без верификации — любые не-exempt страницы редиректят на verify
        blocked = client.get(reverse("accounts:settings_security"))
        assert blocked.status_code == 302
        assert blocked.url.startswith(reverse("2fa:verify"))
        _pass_challenge(client, device)
        assert client.get(reverse("accounts:settings_security")).status_code == 200
