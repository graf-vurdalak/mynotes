# -*- coding: utf-8 -*-
"""Тесты ЛК /accounts/settings/ (Этап 7.2): профиль, настройки приложения, напоминания, пароль."""

import pytest
from django.urls import reverse

from apps.accounts.models import User, UserSettings


@pytest.fixture
def user(db):
    u = User.objects.create_user(email="lk@test.ru", password="Passw0rd-123")
    UserSettings.objects.create(user=u, language="ru")
    return u


def _login(client, user):
    client.force_login(user)
    # 2FA-челлендж обходится пользователем без OTP-устройств
    assert client.get("/dashboard/").status_code == 200


@pytest.mark.django_db
class TestSettingsPage:
    def test_login_required(self, client):
        assert client.get(reverse("accounts:settings")).status_code == 302

    def test_get_renders(self, client, user):
        _login(client, user)
        response = client.get(reverse("accounts:settings"))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Настройки" in content and "Профиль" in content

    def test_get_selects_not_empty(self, client, user):
        """Регресс: .choices plain-поля не доходили до Select — выпадающие были пустыми."""
        _login(client, user)
        content = client.get(reverse("accounts:settings")).content.decode("utf-8")
        for name, expected in (
            ("default_currency", 6), ("timezone", 21), ("transport_tax_month", 12),
        ):
            select = content.split(f'name="{name}"')[1].split("</select>")[0]
            assert select.count("<option") >= expected

    def test_profile_display_name_saved(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "profile", "display_name": "Пётр",
        })
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.display_name == "Пётр"

    def test_email_change_sends_confirmation(self, client, user, mailoutbox):
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "profile", "display_name": user.display_name,
            "new_email": "new@lk.ru",
        })
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.email == "new@lk.ru"
        assert user.email_verified is False
        assert len(mailoutbox) == 1

    def test_email_change_taken_rejected(self, client, user):
        other = User.objects.create_user(email="taken@lk.ru", password="Passw0rd-123")
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "profile", "display_name": "x", "new_email": other.email,
        })
        assert response.status_code == 200  # форма с ошибкой
        user.refresh_from_db()
        assert user.email == "lk@test.ru"

    def test_app_settings_saved(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "app", "language": "ru", "default_currency": "KZT",
            "timezone": "Asia/Almaty",
        })
        assert response.status_code == 302
        us = UserSettings.objects.get(user=user)
        assert us.default_currency == "KZT"
        assert us.timezone == "Asia/Almaty"
        assert us.dark_theme is False  # чекбокс не отправлен

    def test_app_settings_invalid_timezone(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "app", "language": "ru", "default_currency": "RUB",
            "timezone": "Mars/Olympus",
        })
        assert response.status_code == 200
        us = UserSettings.objects.get(user=user)
        assert us.timezone != "Mars/Olympus"

    def test_reminders_saved(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings"), {
            "section": "reminders", "reminder_default_minutes": 15,
            "insurance_reminder_days": 45, "plan_reminder_days": 10,
            "transport_tax_month": 11, "transport_tax_day": 5,
        })
        assert response.status_code == 302
        us = UserSettings.objects.get(user=user)
        assert (us.reminder_default_minutes, us.insurance_reminder_days,
                us.plan_reminder_days, us.transport_tax_month, us.transport_tax_day) == (15, 45, 10, 11, 5)

    def test_timezone_applied_to_request(self, client, user):
        us = UserSettings.objects.get(user=user)
        us.timezone = "Asia/Yekaterinburg"
        us.save()
        _login(client, user)
        response = client.get(reverse("accounts:settings"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestSecurityPage:
    def test_login_required(self, client):
        assert client.get(reverse("accounts:settings_security")).status_code == 302

    def test_renders_with_2fa_status(self, client, user):
        _login(client, user)
        response = client.get(reverse("accounts:settings_security"))
        assert response.status_code == 200
        assert response.context["twofa_enabled"] is False

    def test_password_change(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings_security"), {
            "old_password": "Passw0rd-123",
            "new_password1": "Sup3r-Secret-Pass",
            "new_password2": "Sup3r-Secret-Pass",
        })
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.check_password("Sup3r-Secret-Pass")

    def test_password_change_wrong_old(self, client, user):
        _login(client, user)
        response = client.post(reverse("accounts:settings_security"), {
            "old_password": "nope-not-it",
            "new_password1": "Sup3r-Secret-Pass",
            "new_password2": "Sup3r-Secret-Pass",
        })
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password("Passw0rd-123")
