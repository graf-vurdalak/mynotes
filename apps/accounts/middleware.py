"""ТЗ 8.1: обязательный шаг проверки TOTP/резервного кода после входа.

Сессия пользователя с включённой 2FA не даёт доступа к приложению, пока
OTP-устройство не подтверждено в текущей сессии (``is_verified()``).
Работает для обоих путей входа: email (custom_login) и Яндекс OAuth (allauth) —
здесь нет branch по способу входа, есть единый факт «аутентифицирован, но не верифицирован».
"""

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django_otp import user_has_device
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EXEMPT_PREFIXES = (
    "/2fa/",
    "/login/",
    "/logout/",
    "/signup/",
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/signup/",
    "/accounts/verification-sent/",
    "/accounts/rate-limited/",
    "/accounts/password/",
    "/api/",
    "/static/",
    "/media/",
)


class TwoFactorChallengeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_verified()
            and not request.path_info.startswith(EXEMPT_PREFIXES)
        ):
            # Проверяем наличие устройства НА КАЖДЫЙ запрос: сессия, зашедшая
            # до включения 2FA, обязана получить challenge сразу после включения
            # (фикс ревью №2 — кэш флага в сессии это обходил 7 дней).
            if user_has_device(user):
                target = reverse("2fa:verify")
                sep = "&" if "?" in target else "?"
                return redirect(f"{target}{sep}next={request.get_full_path()}")
        return self.get_response(request)


class UserTimezoneMiddleware:
    """ТЗ 4.1.2: часовой пояс из UserSettings активен для отображения дат в текущем запросе."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        tzname = None
        if user is not None and user.is_authenticated:
            try:
                tzname = user.settings.timezone
            except ObjectDoesNotExist:
                tzname = None
        if tzname:
            try:
                dj_timezone.activate(ZoneInfo(tzname))
            except (ZoneInfoNotFoundError, ValueError):
                dj_timezone.deactivate()
        else:
            # thread-local не наследуется следующему запросу на воркере
            # (анонимы и юзеры без настроек — фикс ревью №8)
            dj_timezone.deactivate()
        return self.get_response(request)
