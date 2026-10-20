"""Сигналы аутентификации: журнал входов (AuthSessionLog) + аудит входа (ТЗ 4.1.2, 8.5)."""

from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed
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
    _sync_user_email_verified(user)
    record_login(request, user, _provider_for(user))


def on_email_confirmed(sender, request, email_address, **kwargs):
    if email_address.user_id:
        _sync_user_email_verified(email_address.user)


def _sync_user_email_verified(user):
    if not user.pk or user.email_verified:
        return
    verified = EmailAddress.objects.filter(
        user_id=user.pk,
        email__iexact=user.email,
        verified=True,
    ).exists()
    if verified:
        type(user).objects.filter(pk=user.pk, email_verified=False).update(
            email_verified=True
        )
        user.email_verified = True


def connect():
    user_logged_in.connect(on_user_logged_in, dispatch_uid="accounts.record_login")
    email_confirmed.connect(
        on_email_confirmed,
        dispatch_uid="accounts.sync_email_verified",
    )
