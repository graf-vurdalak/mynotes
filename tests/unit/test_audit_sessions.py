# -*- coding: utf-8 -*-
"""Тесты журнала входов и аудита (Этап 7.5): фиксация входов, IDOR, критичные действия."""

import pytest
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog, AuthSessionLog, User
from apps.accounts.signals import on_user_logged_in


@pytest.fixture
def user(db):
    return User.objects.create_user(email="audit@test.ru", password="Passw0rd-123")


def _request(ip="10.0.0.9", ua="TestAgent/1.0"):
    rf = RequestFactory()
    return rf.get("/", HTTP_X_FORWARDED_FOR=f"{ip}, 77.88.99.10", HTTP_USER_AGENT=ua)


@pytest.mark.django_db
class TestLoginJournal:
    def test_password_login_recorded(self, client, user):
        client.post("/login/", {"email": user.email, "password": "Passw0rd-123"})
        log = AuthSessionLog.objects.get(user=user)
        assert log.provider == "email"
        assert log.ip_address == "127.0.0.1"
        audit = AuditLog.objects.get(user=user, action="login")
        assert audit.new == {"provider": "email"}

    def test_x_forwarded_for_respected(self):
        """Ревью №1: берётся right-most валидный hop — то, что дописал nginx;
        левый (203.0.113.5) имитирует подделанный клиентом заголовок и игнорируется."""
        request = _request(ip="203.0.113.5")
        request.user = AnonymousUser()
        user = User.objects.create_user(email="xff@test.ru", password="Passw0rd-123")
        user.backend = "django.contrib.auth.backends.ModelBackend"
        on_user_logged_in(sender=User, request=request, user=user)
        assert AuthSessionLog.objects.get(user=user).ip_address == "77.88.99.10"

    def test_yandex_social_provider_mock(self, user):
        request = _request()
        account = SocialAccount.objects.create(user=user, provider="yandex", uid="42")
        # реальный backend соц-логина allauth — социальный провайдер (Ревью №9)
        user.backend = "allauth.socialaccount.providers.yandex.provider"
        on_user_logged_in(sender=User, request=request, user=user)
        log = AuthSessionLog.objects.get(user=user)
        assert log.provider == "yandex"
        assert account.provider == "yandex"

    def test_email_confirmation_autologin_is_email_provider(self, user):
        """Ревью №9: автологин after email-confirmation — account-backend, не social."""
        request = _request()
        user.backend = "allauth.account.auth_backends.AuthenticationBackend"
        on_user_logged_in(sender=User, request=request, user=user)
        assert AuthSessionLog.objects.get(user=user).provider == "email"

    def test_anonymous_signal_skipped(self):
        request = _request()
        on_user_logged_in(sender=User, request=request, user=AnonymousUser())
        assert AuthSessionLog.objects.count() == 0


@pytest.mark.django_db
class TestSessionsPage:
    def test_login_required(self, client):
        assert client.get(reverse("accounts:sessions")).status_code == 302

    def test_only_own_shown(self, client, user):
        other = User.objects.create_user(email="spy@test.ru", password="Passw0rd-123")
        for _ in range(3):
            AuthSessionLog.objects.create(user=user, ip_address="1.1.1.1", user_agent="Mine", provider="email")
        for _ in range(2):
            AuthSessionLog.objects.create(user=other, ip_address="2.2.2.2", user_agent="Foreign", provider="email")
        client.force_login(user)
        response = client.get(reverse("accounts:sessions"))
        rows = list(response.context["sessions"])
        # force_login сам порождает запись журнала; важно: видны только свои
        assert rows  # не пусто
        assert all(r.user_id == user.pk for r in rows)
        content = response.content.decode("utf-8")
        assert "Foreign" not in content and "2.2.2.2" not in content

    def test_capped_at_50(self, client, user):
        AuthSessionLog.objects.bulk_create([
            AuthSessionLog(user=user, ip_address="1.1.1.1", user_agent=f"UA-{i}", provider="email")
            for i in range(55)
        ])
        client.force_login(user)
        response = client.get(reverse("accounts:sessions"))
        assert len(list(response.context["sessions"])) == 50


@pytest.mark.django_db
class TestAuditCriticalActions:
    def test_token_issue_revoke_logged(self, client, user):
        client.force_login(user)
        client.post(reverse("accounts:tokens"), {"name": "аудит-токен", "expires_in_days": "30"})
        issue = AuditLog.objects.get(action="bot_token.issue")
        assert issue.new["name"] == "аудит-токен"
        assert issue.new["expires_in_days"] == 30
        pk = issue.entity_id
        client.post(reverse("accounts:token_revoke", args=[pk]))
        revoke = AuditLog.objects.get(action="bot_token.revoke")
        assert revoke.entity_id == str(pk)

    def test_password_change_logged(self, client, user):
        client.force_login(user)
        client.post(reverse("accounts:settings_security"), {
            "old_password": "Passw0rd-123",
            "new_password1": "Sup3r-Secret-Pass",
            "new_password2": "Sup3r-Secret-Pass",
        })
        assert AuditLog.objects.filter(action="user.password_change", user=user).exists()

    def test_email_change_logged(self, client, user):
        client.force_login(user)
        client.post(reverse("accounts:settings"), {
            "section": "profile", "display_name": "", "new_email": "moved@test.ru",
        })
        audit = AuditLog.objects.get(action="user.email_change")
        assert audit.new["email"] == "moved@test.ru"

    def test_2fa_enable_disable_logged(self, client, user):
        from django_otp.oath import totp
        from apps.accounts import twofactor

        client.force_login(user)
        client.post(reverse("accounts:twofa_setup"), {"action": "create"})
        device = twofactor.TOTPDevice.objects.get(user=user, confirmed=False)
        tok = str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits))
        client.post(reverse("accounts:twofa_setup"), {"action": "confirm", "token": tok})
        assert AuditLog.objects.filter(action="2fa.enable", user=user).exists()
        tok_next = str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=1))
        client.post(reverse("accounts:twofa_disable"), {"token": tok_next})
        assert AuditLog.objects.filter(action="2fa.disable", user=user).exists()

    def test_log_action_without_request(self, user):
        audit = log_action(None, "manual.op", user=user, entity_type="X", entity_id=1)
        assert audit.pk and audit.ip_address is None
