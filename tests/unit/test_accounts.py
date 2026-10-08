# -*- coding: utf-8 -*-
import pytest
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
