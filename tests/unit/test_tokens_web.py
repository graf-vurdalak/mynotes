# -*- coding: utf-8 -*-
"""Тесты web-управления токенами ботов (Этап 7.3): список, выдача, однократный показ, отзыв, IDOR."""

import re

import pytest
from django.utils import timezone
from django.urls import reverse

from apps.accounts.models import AuthToken, User
from apps.accounts.tokens import issue_token, verify_token


@pytest.fixture
def user(db):
    return User.objects.create_user(email="tokens@test.ru", password="Passw0rd-123")


@pytest.fixture
def other(db):
    return User.objects.create_user(email="other@test.ru", password="Passw0rd-123")


def hdr(token):
    return {"HTTP_X_BOT_TOKEN": token}


@pytest.mark.django_db
class TestTokenList:
    def test_login_required(self, client):
        assert client.get(reverse("accounts:tokens")).status_code == 302

    def test_shows_only_own(self, client, user, other):
        issue_token(user, "свой токен")
        issue_token(other, "чужой токен")
        client.force_login(user)
        content = client.get(reverse("accounts:tokens")).content.decode("utf-8")
        assert "свой токен" in content
        assert "чужой токен" not in content

    def test_status_badges(self, client, user):
        plain, token = issue_token(user, "рабочий")
        _, revoked = issue_token(user, "отозванный")
        revoked.is_active = False
        revoked.save()
        _, expired = issue_token(user, "просроченный")
        AuthToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timezone.timedelta(days=1))
        client.force_login(user)
        content = client.get(reverse("accounts:tokens")).content.decode("utf-8")
        assert "Активен" in content and "Отозван" in content and "Просрочен" in content

    def test_original_not_shown_in_list(self, client, user):
        plain, _ = issue_token(user, "токен")
        client.force_login(user)
        content = client.get(reverse("accounts:tokens")).content.decode("utf-8")
        assert plain not in content


@pytest.mark.django_db
class TestTokenCreate:
    def test_create_shows_plain_once(self, client, user):
        client.force_login(user)
        response = client.post(reverse("accounts:tokens"), {"name": "Бот на телефоне", "expires_in_days": ""})
        assert response.status_code == 302
        created_url = response.url
        page = client.get(created_url).content.decode("utf-8")
        # original в HTML ровно один раз и соответствует реально выданному токену
        match = re.search(r">([A-Za-z0-9_-]{40,})</code>", page)
        assert match
        plain = match.group(1)
        token = verify_token(plain)
        assert token is not None and token.user_id == user.pk
        assert "Бот на телефоне" in page

        # второй заход на страницу-результат — оригинала нет
        page2 = client.get(created_url).content.decode("utf-8")
        assert plain not in page2
        assert "Токен больше не показывается" in page2

        # и в списке его нет
        assert plain not in client.get(reverse("accounts:tokens")).content.decode("utf-8")

        # выданный оригинал реально работает через гейтвей
        assert client.post("/api/v1/bot/ping/", **hdr(plain)).status_code == 200

    def test_create_with_expiry(self, client, user):
        client.force_login(user)
        client.post(reverse("accounts:tokens"), {"name": "Dev", "expires_in_days": "30"})
        token = AuthToken.objects.get(user=user)
        assert token.expires_at is not None
        assert (token.expires_at - timezone.now()).days >= 29

    def test_create_requires_name(self, client, user):
        client.force_login(user)
        response = client.post(reverse("accounts:tokens"), {"name": "", "expires_in_days": ""})
        assert response.status_code == 200
        assert AuthToken.objects.filter(user=user).count() == 0


@pytest.mark.django_db
class TestTokenRevoke:
    def test_revoke_own(self, client, user):
        plain, token = issue_token(user, "токен")
        client.force_login(user)
        response = client.post(reverse("accounts:token_revoke", args=[token.pk]))
        assert response.status_code == 302
        token.refresh_from_db()
        assert token.is_active is False
        assert client.post("/api/v1/bot/ping/", **hdr(plain)).status_code == 401

    def test_revoke_other_token_is_404(self, client, user, other):
        _, foreign = issue_token(other, "чужой")
        client.force_login(user)
        response = client.post(reverse("accounts:token_revoke", args=[foreign.pk]))
        assert response.status_code == 404
        foreign.refresh_from_db()
        assert foreign.is_active is True

    def test_created_page_other_token_is_404(self, client, user, other):
        _, foreign = issue_token(other, "чужой")
        client.force_login(user)
        assert client.get(reverse("accounts:token_created", args=[foreign.pk])).status_code == 404
