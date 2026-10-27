import re

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from allauth.account.views import (
    ConfirmEmailView,
    PasswordResetDoneView,
    PasswordResetFromKeyDoneView,
    PasswordResetFromKeyView,
    PasswordResetView,
)
from apps.accounts.views import custom_login, custom_logout, yandex_login_continue
from apps.core.views import media_file

urlpatterns = [
    path("admin/", admin.site.urls),
    # Authorized-прокси файлов (План MinIO): /media/<ключ> читается через default
    # storage с проверкой владельца; публичной раздачи volume'а нет ни в dev, ни в nginx.
    re_path(rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$", media_file, name="media_file"),
    path(
        "accounts/confirm-email/<str:key>/",
        ConfirmEmailView.as_view(template_name="accounts/email_confirm.html"),
        name="account_confirm_email",
    ),
    path(
        "accounts/password/reset/",
        PasswordResetView.as_view(template_name="accounts/password_reset.html"),
        name="account_reset_password",
    ),
    path(
        "accounts/password/reset/done/",
        PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="account_reset_password_done",
    ),
    re_path(
        r"^accounts/password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        PasswordResetFromKeyView.as_view(
            template_name="accounts/password_reset_from_key.html"
        ),
        name="account_reset_password_from_key",
    ),
    path(
        "accounts/password/reset/key/done/",
        PasswordResetFromKeyDoneView.as_view(
            template_name="accounts/password_reset_from_key_done.html"
        ),
        name="account_reset_password_from_key_done",
    ),
    path("accounts/", include("allauth.urls")),
    path("2fa/", include("apps.accounts.twofactor_urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/docs/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/v1/bot/", include("apps.api.urls")),
    path("login/yandex/", yandex_login_continue, name="yandex_login_continue"),
    path("login/", custom_login, name="login"),
    path("logout/", custom_logout, name="logout"),
    path("", include("apps.accounts.urls")),
    path("dashboard/", include("apps.core.urls")),
    path("vehicles/", include("apps.vehicles.urls")),
    path("planner/", include("apps.planner.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("reports/", include("apps.reports.urls")),
    path("search/", include("apps.search.urls")),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
]

if settings.DEBUG:
    #import debug_toolbar
    #urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    # /media/ в DEBUG тоже идёт через authorized-прокси выше (не public static()).
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
