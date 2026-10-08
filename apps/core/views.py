from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.utils import timezone

from apps.core.i18n import t
from apps.core.media import file_owner_ids
from apps.vehicles import services

_WEEKDAYS = tuple(t(f"date.wd_full.{i}") for i in range(1, 8))
_MONTHS = (None,) + tuple(t(f"date.month_gen.{i}") for i in range(1, 13))


def _greeting():
    hour = timezone.now().hour
    if hour < 12:
        return t("dashboard.greeting_morning")
    if hour < 18:
        return t("dashboard.greeting_day")
    return t("dashboard.greeting_evening")


def _format_date(d):
    weekday = _WEEKDAYS[d.weekday()].capitalize()
    return f"{weekday}, {d.day} {_MONTHS[d.month]} {d.year}"


@login_required
def dashboard(request):
    data = services.dashboard_overview(request.user)

    now = timezone.now()
    dates_str = _format_date(now.date())
    reminder_count = (
        len(data["expiring_insurances"])
        + data["unpaid_fines_count"]
        + len(data["upcoming_planned"])
    )

    context = {
        **data,
        "greeting": _greeting(),
        "today_str": dates_str,
        "reminders_count": reminder_count,
    }
    return render(request, "core/dashboard.html", context)


@login_required
def media_file(request, path):
    """Authorized-прокси файлов: доступ к хранилищу только через default storage backend.

    Владелец файла определяется реестром apps.core.media (404 для чужих ключей —
    не раскрывает существование объекта). FileSystemStorage/S3 взаимозаменяемы:
    в БД лежат относительные ключи, endpoint хранилища браузеру неизвестен.
    """
    if request.user.pk not in file_owner_ids(path):
        raise Http404
    try:
        if not default_storage.exists(path):
            raise Http404
        file = default_storage.open(path, "rb")
    except SuspiciousFileOperation as exc:
        raise Http404 from exc
    return FileResponse(file, as_attachment=False)