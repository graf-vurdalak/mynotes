# -*- coding: utf-8 -*-
import pytest
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
