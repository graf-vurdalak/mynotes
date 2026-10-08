import re

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.accounts.views import custom_login, custom_logout
from apps.core.views import media_file

urlpatterns = [
    path("admin/", admin.site.urls),
    # Authorized-прокси файлов (План MinIO): /media/<ключ> читается через default
    # storage с проверкой владельца; публичной раздачи volume'а нет ни в dev, ни в nginx.
    re_path(rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$", media_file, name="media_file"),
    path("accounts/", include("allauth.urls")),
    path("2fa/", include("apps.accounts.twofactor_urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/docs/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/v1/bot/", include("apps.api.urls")),
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
