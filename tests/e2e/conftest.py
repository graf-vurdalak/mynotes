import pytest
from playwright.sync_api import Browser, Page, sync_playwright


@pytest.fixture
def browser(live_server) -> Browser:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser, live_server, settings) -> Page:
    settings.OTP_TOTP_THROTTLE_FACTOR = 0
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()

    def block_external_assets(route):
        if route.request.url.startswith(live_server.url):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", block_external_assets)
    yield page
    context.close()
