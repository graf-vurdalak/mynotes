# -*- coding: utf-8 -*-
"""Тесты auth-слоя токенов Telegram-ботов (Этап 4.1)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import AuthToken
from apps.accounts.tokens import digest_token, issue_token, revoke_token, verify_token

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="bot@test.ru", password="pass12345")


@pytest.mark.django_db
def test_issue_token_returns_plaintext_once_and_stores_hash(user):
    plain, token = issue_token(user, "Телефон")
    assert len(plain) >= 48
    assert token.token_hash != plain
    # В БД хранится только HMAC-хэш с пепром
    assert token.token_hash == digest_token(plain)


@pytest.mark.django_db
def test_verify_valid_token_updates_usage(user):
    plain, _ = issue_token(user, "web")
    token = verify_token(plain, ip="10.0.0.1")
    assert token is not None and token.user_id == user.id
    token.refresh_from_db()
    assert token.last_used_at is not None
    assert token.last_used_ip == "10.0.0.1"


@pytest.mark.django_db
def test_verify_unknown_token_returns_none(user):
    assert verify_token("не-существующий-токен") is None


@pytest.mark.django_db
def test_verify_empty_returns_none(user):
    assert verify_token("") is None


@pytest.mark.django_db
def test_revoked_token_is_rejected(user):
    plain, token = issue_token(user, "temp")
    revoke_token(token)
    assert verify_token(plain) is None


@pytest.mark.django_db
def test_expired_token_is_rejected(user):
    plain, token = issue_token(user, "old", expires_in_days=1)
    AuthToken.objects.filter(pk=token.pk).update(
        expires_at=timezone.now() - timedelta(seconds=5)
    )
    assert verify_token(plain) is None


@pytest.mark.django_db
def test_inactive_user_rejected(user):
    plain, _ = issue_token(user, "u")
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert verify_token(plain) is None


@pytest.mark.django_db
def test_revoke_is_idempotent(user):
    _, token = issue_token(user, "x")
    revoke_token(token)
    revoke_token(token)  # не падает
    assert token.is_active is False


@pytest.mark.django_db
def test_digest_deterministic_and_pepper_keyed():
    assert digest_token("abc") == digest_token("abc")
    assert digest_token("abc") != digest_token("abd")
