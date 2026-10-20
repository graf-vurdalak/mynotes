# -*- coding: utf-8 -*-
from uuid import uuid4

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_login_page_loads(client):
    url = reverse("login")
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Войти" in content
    assert "Зарегистрироваться" in content
    assert "Войти через Яндекс" in content


@pytest.mark.django_db
def test_login_page_has_csrf(client):
    url = reverse("login")
    response = client.get(url)
    assert b"csrfmiddlewaretoken" in response.content


@pytest.mark.django_db
def test_login_page_has_yandex_oauth_link(client):
    url = reverse("login")
    response = client.get(url)
    content_lower = response.content.decode("utf-8").lower()
    assert "yandex" in content_lower or "яндекс" in content_lower


@pytest.mark.django_db
def test_signup_shows_email_verification_notice(client, mailoutbox):
    email = f"signup-{uuid4().hex}@example.org"
    response = client.post(
        reverse("accounts:signup"),
        {
            "email": email,
            "display_name": "Signup Test",
            "password": "strong-password-742",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:verification_sent")

    response = client.get(response.url)
    assert response.status_code == 200
    assert "Письмо с подтверждением отправлено на ваш email" in response.content.decode("utf-8")
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_email_confirmation_link_verifies_address_and_allows_login(client):
    user = get_user_model().objects.create_user(
        email="confirmation-test@example.org",
        password="strong-password-742",
    )
    address = EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
    )
    url = reverse(
        "account_confirm_email",
        kwargs={"key": EmailConfirmationHMAC(address).key},
    )

    response = client.get(url)
    assert response.status_code == 200

    response = client.post(url)
    assert response.status_code == 302
    address.refresh_from_db()
    assert address.verified
    user.refresh_from_db()
    assert user.email_verified

    response = client.post(
        reverse("login"),
        {"email": user.email, "password": "strong-password-742"},
    )
    assert response.status_code == 302
    assert response.url == "/dashboard/"
    assert str(client.session["_auth_user_id"]) == str(user.pk)


@pytest.mark.django_db
def test_yandex_verified_email_sets_user_email_verified(client):
    user = get_user_model().objects.create_user(
        email="yandex-test@example.org",
        password="strong-password-742",
    )
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=True,
    )
    SocialAccount.objects.create(user=user, provider="yandex", uid="yandex-test-uid")

    client.force_login(
        user,
        backend="allauth.socialaccount.auth_backends.AuthenticationBackend",
    )

    user.refresh_from_db()
    assert user.email_verified


@pytest.mark.django_db
def test_yandex_oauth_confirmation_auto_submits_with_fallback(client):
    response = client.get(
        "/accounts/yandex/login/?process=oauth&next=%2Faccounts%2Flogin%2F"
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert (
        'id="socialaccount-login-form" method="post" '
        'action="/login/yandex/?process=oauth&amp;next=%2Faccounts%2Flogin%2F"'
    ) in content
    assert 'getElementById("socialaccount-login-form").submit()' in content
    assert "Продолжить" in content


@pytest.mark.django_db
@override_settings(
    SOCIALACCOUNT_PROVIDERS={
        "yandex": {
            "APP": {"client_id": "test-client-id", "secret": "test-secret"},
            "SCOPE": ["login:email", "login:info"],
        }
    }
)
def test_yandex_login_post_returns_safe_redirect_page(client):
    response = client.post("/login/yandex/?process=oauth")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "window.location.replace" in content
    assert "https://oauth.yandex.com/authorize?" in content
