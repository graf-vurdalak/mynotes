from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.custom_signup, name="signup"),
    path("verification-sent/", views.email_verification_sent, name="verification_sent"),
    path("rate-limited/", views.rate_limited, name="rate_limited"),
    # Личный кабинет (ТЗ 9.3) — всеauth-роуты выше по /accounts/ не конфликтуют:
    # не совпавшие пути проваливаются в этот include.
    path("accounts/settings/", views.account_settings, name="settings"),
    path("accounts/settings/security/", views.account_security, name="settings_security"),
    path("accounts/tokens/", views.bot_tokens, name="tokens"),
    path("accounts/tokens/created/<uuid:pk>/", views.bot_token_created, name="token_created"),
    path("accounts/tokens/<uuid:pk>/revoke/", views.bot_token_revoke, name="token_revoke"),
    path("accounts/settings/security/2fa/", views.twofa_setup, name="twofa_setup"),
    path("accounts/settings/security/2fa/backup/", views.twofa_backup, name="twofa_backup"),
    path("accounts/settings/security/2fa/regenerate/", views.twofa_regenerate, name="twofa_regenerate"),
    path("accounts/settings/security/2fa/disable/", views.twofa_disable, name="twofa_disable"),
    path("accounts/sessions/", views.account_sessions, name="sessions"),
]
