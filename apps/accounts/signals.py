"""Сигналы аутентификации: журнал входов (AuthSessionLog) + аудит входа (ТЗ 4.1.2, 8.5)."""

from django.contrib.auth.signals import user_logged_in

from .audit import record_login


def _provider_for(user) -> str:
    """email — обычный парольный вход и автологин подтверждения allauth;
    socialaccount-backend — провайдер OAuth (Яндекс).

    Ревью №9: ``"allauth" in backend`` ловит и account-backend (подтверждение
    email логинит через allauth без SocialAccount) — тех ошибочно писалось в журнал.
    """
    backend = getattr(user, "backend", "") or ""
    if "socialaccount" in backend:
        from allauth.socialaccount.models import SocialAccount

        account = SocialAccount.objects.filter(user=user).order_by("-date_joined").first()
        return account.provider if account else "social"
    return "email"


def on_user_logged_in(sender, request, user, **kwargs):
    # request может отсутствовать (programmatic login), а user — быть анонимным
    if request is None or user is None or not user.is_authenticated:
        return
    record_login(request, user, _provider_for(user))


def connect():
    user_logged_in.connect(on_user_logged_in, dispatch_uid="accounts.record_login")
