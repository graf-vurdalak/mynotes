# -*- coding: utf-8 -*-
from uuid import uuid4
from urllib.parse import urlsplit

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
def test_password_reset_page_is_centered_and_linked_from_login(client):
    response = client.get(reverse("login"))
    assert f'href="{reverse("account_reset_password")}"'.encode() in response.content

    response = client.get(reverse("account_reset_password"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert any(template.name == "accounts/password_reset.html" for template in response.templates)
    assert b'csrfmiddlewaretoken' in response.content


@pytest.mark.django_db
def test_password_reset_done_page_is_centered(client):
    response = client.get(reverse("account_reset_password_done"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert "Проверьте почту" in content
    assert any(
        template.name == "accounts/password_reset_done.html"
        for template in response.templates
    )


@pytest.mark.django_db
def test_password_reset_from_key_page_uses_styled_template(client):
    response = client.get(
        reverse(
            "account_reset_password_from_key",
            kwargs={"uidb36": "invalid", "key": "invalid"},
        )
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert "Ссылка недействительна" in content
    assert any(
        template.name == "accounts/password_reset_from_key.html"
        for template in response.templates
    )


@pytest.mark.django_db
def test_password_reset_from_key_done_page_is_centered(client):
    response = client.get(reverse("account_reset_password_from_key_done"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert "Пароль успешно изменён" in content
    assert f'href="{reverse("login")}"'.encode() in response.content
    assert any(
        template.name == "accounts/password_reset_from_key_done.html"
        for template in response.templates
    )


@pytest.mark.django_db
def test_password_reset_request_sends_email(client, mailoutbox):
    email = "password-reset@example.org"
    user = get_user_model().objects.create_user(email=email, password="strong-password-742")
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)

    response = client.post(reverse("account_reset_password"), {"email": email})

    assert response.status_code == 302
    assert response.url == reverse("account_reset_password_done")
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [email]
    assert "/accounts/password/reset/key/" in mailoutbox[0].body

    reset_link = next(
        part.strip("<>().,")
        for part in mailoutbox[0].body.split()
        if "/accounts/password/reset/key/" in part
    )
    response = client.get(urlsplit(reset_link).path, follow=True)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert 'name="password1"' in content
    assert 'name="password2"' in content
    assert any(
        template.name == "accounts/password_reset_from_key.html"
        for template in response.templates
    )


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
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert "Письмо с подтверждением отправлено на ваш email" in content
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
    content = response.content.decode("utf-8")
    assert 'class="min-h-screen flex items-center justify-center' in content
    assert "Подтвердить email" in content
    assert any(
        template.name == "accounts/email_confirm.html"
        for template in response.templates
    )

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
