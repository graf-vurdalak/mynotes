from django.urls import path

from . import views

app_name = "api"

# Подключается в config/urls.py как path("api/v1/bot/", include("apps.api.urls"))
urlpatterns = [
    path("ping/", views.BotPingView.as_view(), name="bot_ping"),
    path("ingest/", views.BotIngestView.as_view(), name="bot_ingest"),
    path("upload/", views.BotUploadView.as_view(), name="bot_upload"),
    path(
        "references/<str:ref_type>/",
        views.BotReferenceView.as_view(),
        name="bot_reference",
    ),
]
