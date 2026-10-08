from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django_otp.oath import totp
from playwright.sync_api import Page

from apps.accounts import twofactor

User = get_user_model()

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="playwright@example.test", password="TestPassword-12345"
    )


@pytest.fixture
def two_factor_user(user, settings):
    settings.OTP_TOTP_THROTTLE_FACTOR = 0
    device = twofactor.begin_enable(user)
    setup_token = str(
        totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
    )
    assert twofactor.confirm_device(device, setup_token)
    return user, device


def open_login(page: Page, live_server, user):
    page.goto(f"{live_server.url}{reverse('login')}", wait_until="domcontentloaded")
    page.locator("#id_email").fill(user.email)
    page.locator("#id_password").fill("TestPassword-12345")
    page.locator("form[action='/login/'] button[type=submit]").click()


def test_login_and_create_personal_event(user, page, live_server):
    open_login(page, live_server, user)
    page.wait_for_url(f"{live_server.url}/dashboard/")

    page.goto(
        f"{live_server.url}{reverse('planner:event_create')}?next={reverse('planner:feed')}",
        wait_until="domcontentloaded",
    )
    title = "Playwright event"
    page.locator("#id_title").fill(title)
    page.locator("#id_date_start").fill((date.today() + timedelta(days=1)).isoformat())
    page.locator("#event-form button[type=submit]").click()

    page.wait_for_url(f"{live_server.url}{reverse('planner:feed')}")
    assert page.get_by_text(title).is_visible()


def test_login_requires_otp_then_allows_settings(two_factor_user, page: Page, live_server):
    user, device = two_factor_user
    open_login(page, live_server, user)
    page.wait_for_url("**/2fa/verify/**")
    challenge_token = str(
        totp(
            device.bin_key,
            step=device.step,
            t0=device.t0,
            digits=device.digits,
            drift=1,
        )
    )
    page.locator("#id_token").fill(challenge_token)
    page.locator("form").first.locator("button[type=submit]").click()
    page.wait_for_url(f"{live_server.url}/dashboard/")

    response = page.goto(
        f"{live_server.url}{reverse('accounts:settings_security')}",
        wait_until="domcontentloaded",
    )
    assert response is not None and response.status == 200
