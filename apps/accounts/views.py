from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django_ratelimit.core import is_ratelimited
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.contrib import messages
from django_otp import DEVICE_ID_SESSION_KEY, login as otp_login, user_has_device
from allauth.account.models import EmailAddress
from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
from allauth.socialaccount.providers.yandex.views import YandexOAuth2Adapter

from apps.core.i18n import t
from . import twofactor
from .audit import client_ip, log_action
from .forms import (
    AppSettingsForm,
    IssueTokenForm,
    ProfileForm,
    RemindersForm,
    SignupForm,
    StyledPasswordChangeForm,
)
from .models import AuthToken, AuthSessionLog, UserSettings
from .tokens import issue_token, revoke_token

# Ревью №3: одноразовые секреты (оригиналы токенов, резервные коды 2FA) НЕ должны
# персиститься в django_session (cached_db пишет в Postgres plaintext) — живём только
# в Redis-кэше с коротким TTL; в сессии — лишь маркеры {pk: True}.
_ISSUED_SESSION_KEY = "issued_bot_tokens"
_ONE_TIME_TOKEN_TTL = 300
_ONE_TIME_BACKUP_TTL = 300
_yandex_oauth_login = OAuth2LoginView.adapter_view(YandexOAuth2Adapter)


def _one_time_token_key(pk):
    return f"onetime:token:{pk}"


def _one_time_backup_key(user_pk):
    return f"onetime:backup:{user_pk}"


def _rate_blocked(request, group: str, rate: str) -> bool:
    """django-ratelimit по IP — ТЗ 8.4.

    Ключ — ``audit.client_ip`` (right-most валидный hop XFF, неподделываемый за
    нашим nginx) — тот же источник, что и журнал входов, чтобы лимит и аудит
    не расходились. Порог читается из settings в момент вызова (как RATELIMIT_API).
    """
    return is_ratelimited(
        request,
        group=group,
        key=lambda group, request: client_ip(request) or "unknown",
        rate=rate,
        method="POST",
        increment=True,
    )


@sensitive_post_parameters()
def custom_login(request):
    if request.method == "POST" and _rate_blocked(
        request, "accounts.login", settings.RATELIMIT_LOGIN
    ):
        return rate_limited(request, "Rate limit exceeded")
    next_url = request.GET.get("next", "/dashboard/")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        if email and password:
            user = authenticate(request, username=email, password=password)
            if user is not None:
                auth_login(request, user)
                return redirect(next_url)
            else:
                error = t("auth.invalid_credentials")
    else:
        error = ""

    return render(request, "accounts/login.html", {"next": next_url, "error": error})


def yandex_login_continue(request):
    response = _yandex_oauth_login(request)
    location = response.get("Location", "")
    target = urlsplit(location)
    if (
        request.method == "POST"
        and response.status_code == 302
        and target.scheme == "https"
        and target.netloc == "oauth.yandex.com"
        and target.path == "/authorize"
    ):
        return render(
            request,
            "socialaccount/oauth_redirect.html",
            {"authorize_url": location},
        )
    return response


def custom_signup(request):
    # Верификационные письма в UI создаются только регистрацией (allauth- resend
    # /accounts/email/ нигде не выставлен), поэтому лимит ТЗ 8.4 стоит на signup POST.
    if request.method == "POST" and _rate_blocked(
        request, "accounts.signup", settings.RATELIMIT_SIGNUP
    ):
        return rate_limited(request, "Rate limit exceeded")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            EmailAddress.objects.add_email(
                request, user, user.email, confirm=True, signup=True
            )
            return redirect("accounts:verification_sent")
    else:
        form = SignupForm()

    return render(request, "accounts/signup.html", {"form": form})


def email_verification_sent(request):
    return render(request, "accounts/email_verification_sent.html")


def rate_limited(request, reason=""):
    status = 429 if "rate" in reason.lower() else 400
    return render(
        request,
        "accounts/rate_limited.html",
        status=status,
    )


def custom_logout(request):
    if request.method == "POST":
        auth_logout(request)
        return redirect("login")
    return render(request, "accounts/logout.html")


class TokenChallengeForm(forms.Form):
    token = forms.CharField(
        max_length=16,
        widget=forms.TextInput(attrs={
            "placeholder": "000000",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "autofocus": True,
            "class": "w-full px-4 py-3 border border-slate-200 rounded-lg text-center text-lg font-mono tracking-[0.5em] focus:ring-2 focus:ring-blue-500 focus:border-transparent transition",
        }),
    )


@sensitive_post_parameters("token")
def otp_verify(request):
    """Шаг проверки 2FA после логина (ТЗ 8.1); вызывается TwoFactorChallengeMiddleware.

    Код может быть TOTP или одноразовым резервным (consumed при успехе).
    """
    next_url = request.POST.get("next") or request.GET.get("next") or "/dashboard/"
    if not request.user.is_authenticated:
        return redirect(reverse("login") + f"?next={request.get_full_path()}")
    if not user_has_device(request.user):
        # 2FA отключена (устройство проверено live в middleware) — остаётся
        # информативная страница, challenge больше не нужен
        return render(request, "accounts/otp_verify.html", {
            "disabled": True,
            "next": next_url,
        })

    form = TokenChallengeForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        device = twofactor.verify_any_token(request.user, form.cleaned_data["token"])
        if device is not None:
            otp_login(request, device)
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
                return redirect(next_url)
            return redirect("/dashboard/")
        error = t("auth.otp_error")

    return render(request, "accounts/otp_verify.html", {
        "form": form,
        "error": error,
        "next": next_url,
        "disabled": False,
    })


def account_settings(request):
    """ЛК /accounts/settings/ (ТЗ 4.1.2, 9.3): профиль, приложение, напоминания.

    Один POST на секцию (hidden field ``section``) — три независимые формы.
    """
    user = request.user
    us, _ = UserSettings.objects.get_or_create(user=user)

    profile_form = app_form = reminders_form = None
    section = request.POST.get("section") if request.method == "POST" else None

    if section == "profile":
        profile_form = ProfileForm(request.POST, request.FILES, instance=user)
        if profile_form.is_valid():
            new_email = profile_form.cleaned_data.get("new_email")
            profile_form.save()
            if new_email:
                EmailAddress.objects.add_email(request, user, new_email, confirm=True)
                log_action(
                    request, "user.email_change",
                    entity_type="User", entity_id=user.pk, new={"email": new_email},
                )
                messages.success(request, t("settings.email_change_sent"))
            else:
                messages.success(request, t("settings.saved"))
            return redirect("accounts:settings")
    elif section == "app":
        app_form = AppSettingsForm(request.POST, instance=us)
        if app_form.is_valid():
            app_form.save()
            messages.success(request, t("settings.saved"))
            return redirect("accounts:settings")
    elif section == "reminders":
        reminders_form = RemindersForm(request.POST, instance=us)
        if reminders_form.is_valid():
            reminders_form.save()
            messages.success(request, t("settings.saved"))
            return redirect("accounts:settings")

    return render(request, "accounts/settings.html", {
        "profile_form": profile_form or ProfileForm(instance=user),
        "app_form": app_form or AppSettingsForm(instance=us),
        "reminders_form": reminders_form or RemindersForm(instance=us),
        "active_page": "settings",
    })


def account_security(request):
    """Вкладка «Безопасность»: смена пароля + статус 2FA (включение/выключение — 7.4)."""
    user = request.user
    form = StyledPasswordChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "user.password_change", entity_type="User", entity_id=user.pk)
        messages.success(request, t("settings.password_changed"))
        return redirect("accounts:settings_security")

    return render(request, "accounts/settings_security.html", {
        "form": form,
        "twofa_enabled": twofactor.is_enabled(user),
        "backup_codes_left": twofactor.backup_codes_left(user),
        "active_page": "settings",
    })


def bot_tokens(request):
    """ЛК /accounts/tokens/ (ТЗ 4.1.3, 9.3): список своих токенов + выдача (issue_token).

    Видимость фильтруется по ``request.user`` (защита от IDOR). Оригинал нового токена
    кладётся в сессию и показывается ровно один раз на странице-результате.
    """
    user = request.user
    tokens = AuthToken.objects.filter(user=user)
    create_form = IssueTokenForm()
    if request.method == "POST":
        create_form = IssueTokenForm(request.POST)
        if create_form.is_valid():
            plain, token = issue_token(
                user,
                create_form.cleaned_data["name"],
                expires_in_days=create_form.cleaned_data.get("expires_in_days"),
            )
            cache.set(_one_time_token_key(token.pk), plain, _ONE_TIME_TOKEN_TTL)
            issued = request.session.get(_ISSUED_SESSION_KEY, {})
            issued[str(token.pk)] = True
            request.session[_ISSUED_SESSION_KEY] = issued
            log_action(
                request, "bot_token.issue",
                entity_type="AuthToken", entity_id=token.pk,
                new={"name": token.name, "expires_in_days": create_form.cleaned_data.get("expires_in_days")},
            )
            messages.success(request, t("tokens.issued"))
            return redirect("accounts:token_created", pk=token.pk)

    return render(request, "accounts/tokens.html", {
        "tokens": tokens,
        "create_form": create_form,
        "now": timezone.now(),
        "active_page": "settings",
    })


def bot_token_created(request, pk):
    """Однократный показ оригинала токена (ТЗ 8.2). После просмотра ключ удаляется."""
    token = get_object_or_404(AuthToken, pk=pk, user=request.user)
    issued = request.session.get(_ISSUED_SESSION_KEY, {})
    issued.pop(str(token.pk), None)
    if issued:
        request.session[_ISSUED_SESSION_KEY] = issued
    else:
        request.session.pop(_ISSUED_SESSION_KEY, None)
    plain = cache.get(_one_time_token_key(token.pk))
    cache.delete(_one_time_token_key(token.pk))
    already_shown = plain is None
    return render(request, "accounts/token_created.html", {
        "token": token,
        "plain": plain,
        "already_shown": already_shown,
        "active_page": "settings",
    })


def bot_token_revoke(request, pk):
    """POST-отзыв только своего токена (get_object_or_404 с фильтром по user — IDOR)."""
    if request.method != "POST":
        return redirect("accounts:tokens")
    token = get_object_or_404(AuthToken, pk=pk, user=request.user)
    revoke_token(token)
    log_action(
        request, "bot_token.revoke",
        entity_type="AuthToken", entity_id=token.pk, new={"name": token.name},
    )
    messages.success(request, t("tokens.revoked"))
    return redirect("accounts:tokens")


_PENDING_DEVICE_SESSION_KEY = "twofa_pending_device"


def _pending_or_none(request):
    pk = request.session.get(_PENDING_DEVICE_SESSION_KEY)
    return twofactor.get_unconfirmed_device(request.user, pk)


def twofa_setup(request):
    """Мастер включения 2FA (ТЗ 8.1): создать → показать QR → подтвердить кодом → резервные коды один раз."""
    if twofactor.is_enabled(request.user):
        return redirect("accounts:settings_security")

    action = request.POST.get("action") if request.method == "POST" else None

    if action == "create":
        device = twofactor.begin_enable(request.user)
        request.session[_PENDING_DEVICE_SESSION_KEY] = str(device.pk)
        return render(request, "accounts/twofa_setup.html", _setup_ctx(device))

    if action == "cancel":
        device = _pending_or_none(request)
        if device is not None:
            device.delete()
        request.session.pop(_PENDING_DEVICE_SESSION_KEY, None)
        return redirect("accounts:settings_security")

    device = _pending_or_none(request)
    if device is None:
        return redirect("accounts:settings_security")

    if action == "confirm":
        form = TokenChallengeForm(request.POST)
        token = form.data.get("token", "") if form.data else ""
        if twofactor.confirm_device(device, token):
            request.session.pop(_PENDING_DEVICE_SESSION_KEY, None)
            # Ревью №2: middleware теперь проверяет наличие устройства на каждый
            # запрос (без кэша) — текущую сессию мастера верифицируем явно
            # (persistent_id читает OTPMiddleware; без ре-emit user_logged_in).
            request.session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            codes = twofactor.generate_backup_codes(request.user)
            cache.set(_one_time_backup_key(request.user.pk), codes, _ONE_TIME_BACKUP_TTL)
            log_action(request, "2fa.enable", entity_type="TOTPDevice", entity_id=device.pk)
            messages.success(request, t("settings.2fa_enabled"))
            return redirect("accounts:twofa_backup")
        ctx = _setup_ctx(device)
        ctx["error"] = t("auth.otp_error")
        return render(request, "accounts/twofa_setup.html", ctx)

    return render(request, "accounts/twofa_setup.html", _setup_ctx(device))


def _setup_ctx(device):
    return {
        "device": device,
        "qr_svg": twofactor.provisioning_qr(device),
        "secret": twofactor.provisioning_secret(device),
        "active_page": "settings",
    }


def twofa_backup(request):
    """Однократный показ резервных кодов после включения/пересоздания (ТЗ 8.1)."""
    codes = cache.get(_one_time_backup_key(request.user.pk))
    if not codes:
        return redirect("accounts:settings_security")
    cache.delete(_one_time_backup_key(request.user.pk))
    return render(request, "accounts/twofa_backup.html", {
        "codes": codes,
        "active_page": "settings",
    })


def twofa_regenerate(request):
    """POST: перевыпуск резервных кодов (старые сбрасываются), показ один раз."""
    if request.method != "POST" or not twofactor.is_enabled(request.user):
        return redirect("accounts:settings_security")
    codes = twofactor.generate_backup_codes(request.user)
    cache.set(_one_time_backup_key(request.user.pk), codes, _ONE_TIME_BACKUP_TTL)
    log_action(request, "2fa.backup_regen", entity_type="StaticDevice")
    messages.success(request, t("settings.2fa_codes_regenerated"))
    return redirect("accounts:twofa_backup")


@sensitive_post_parameters("token")
def twofa_disable(request):
    """POST: выключение 2FA с подтверждением текущим OTP/резервным кодом (ТЗ 4.1.2)."""
    if request.method != "POST":
        return redirect("accounts:settings_security")
    if not twofactor.is_enabled(request.user):
        return redirect("accounts:settings_security")

    token = (request.POST.get("token") or "").strip()
    device = twofactor.verify_any_token(request.user, token)
    if device is None:
        messages.error(request, t("auth.otp_error"))
        return redirect("accounts:settings_security")

    twofactor.disable(request.user)
    log_action(request, "2fa.disable", entity_type="User", entity_id=request.user.pk)
    request.session.pop(_PENDING_DEVICE_SESSION_KEY, None)
    cache.delete(_one_time_backup_key(request.user.pk))
    # снимаем OTP-верификацию сессии (DEVICE_ID указывает на удалённое устройство)
    request.session.pop(DEVICE_ID_SESSION_KEY, None)
    messages.success(request, t("settings.2fa_disabled"))
    return redirect("accounts:settings_security")


def account_sessions(request):
    """Журнал входов /accounts/sessions/ (ТЗ 4.1.2, 9.3): последние 50 своих сессий."""
    sessions = AuthSessionLog.objects.filter(user=request.user)[:50]
    return render(request, "accounts/sessions.html", {
        "sessions": sessions,
        "active_page": "settings",
    })
