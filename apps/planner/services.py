"""Бизнес-сервисы Записной книжки (ТЗ 4.3, 5.4).

Гарантия скоупов, защита от IDOR, смена статусов с историей,
развёртка повторяющихся событий, прогресс проектов и поиск.
"""

from __future__ import annotations

import calendar as cal
import datetime as dt

from django.utils import timezone

from .models import Comment, Event, Project, Scope, Status, StatusHistory

WEEKDAY_NAMES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


# ------------------------------------------------------------------
# Скоупы и стартовые данные
# ------------------------------------------------------------------

def guarantee_scopes(user) -> dict[str, Scope]:
    """Создаёт (если нужно) скоупы «Личное» и «Рабочее» для пользователя."""
    existing = {s.code: s for s in Scope.objects.filter(user=user)}
    missing = [code for code, _ in Scope.CODES if code not in existing]
    if missing:
        names = dict(Scope.CODES)
        Scope.objects.bulk_create([Scope(user=user, code=c, name=names[c]) for c in missing])
        existing = {s.code: s for s in Scope.objects.filter(user=user)}
    return existing


def get_scope(user, code: str) -> Scope:
    scopes = guarantee_scopes(user)
    return scopes[code]


def ensure_statuses(user, work_scope: Scope) -> list[Status]:
    """Создаёт 5 системных статусов ТЗ 4.3.3 для пользователя (идемпотентно)."""
    existing = {s.code: s for s in Status.objects.filter(user=user, code__in=[c for c, _, _ in Status.SYSTEM_CODES])}
    statuses = []
    for idx, (code, name, color) in enumerate(Status.SYSTEM_CODES):
        status = existing.get(code)
        if status is None:
            status = Status.objects.create(
                user=user, code=code, name=name, color=color,
                sort_order=idx, is_system=True,
            )
        elif status.is_deleted:
            status.is_deleted = False
            status.save(update_fields=["is_deleted", "updated_at"])
        statuses.append(status)
    return statuses


def default_status_for(user) -> Status | None:
    """Стартовый статус новой задачи — «Новый»."""
    return (
        Status.objects.filter(user=user, is_deleted=False, code="new")
        .order_by("sort_order")
        .first()
    )


# ------------------------------------------------------------------
# IDOR-слой (по образцу apps/vehicles/services.py)
# ------------------------------------------------------------------

def owned_queryset(model, user, **filters):
    return model.objects.filter(user=user, is_deleted=False, **filters)


def get_owned(model, user, pk, **filters):
    return model.objects.filter(pk=pk, user=user, is_deleted=False, **filters).first()


# ------------------------------------------------------------------
# События / задачи
# ------------------------------------------------------------------

def change_event_status(event: Event, new_status: Status | None, user) -> Event:
    """Меняет статус задачи, пишет StatusHistory и completed_at (ТЗ 4.3.3)."""
    old_status = event.status
    if old_status == new_status:
        return event
    event.status = new_status
    is_done_code = new_status.code if new_status else None
    if is_done_code == "done":
        if event.completed_at is None:
            event.completed_at = timezone.now()
    else:
        event.completed_at = None
    event.save(update_fields=["status", "completed_at", "updated_at"])
    StatusHistory.objects.create(
        event=event, from_status=old_status, to_status=new_status, changed_by=user
    )
    return event


def project_progress(project: Project) -> int | None:
    """% выполненных задач для рабочего проекта; для личного — None."""
    if project.scope.code != Scope.WORK:
        return None
    total = owned_queryset(Event, project.user, project=project, scope=project.scope).count()
    if total == 0:
        return 0
    done = owned_queryset(
        Event, project.user, project=project, scope=project.scope, status__code="done"
    ).count()
    return round(done * 100 / total)


def search_events(user, scope_code: str | None, query: str, limit: int = 50):
    """Поиск по названию, описанию и тегам (МVP без tsvector)."""
    from django.db.models import Q

    qs = owned_queryset(Event, user)
    if scope_code:
        qs = qs.filter(scope__code=scope_code)
    term = query.strip()
    if not term:
        return qs.none()
    return qs.filter(
        Q(title__icontains=term) | Q(description__icontains=term) | Q(tags__contains=[term])
    ).select_related("scope", "project", "status")[:limit]


# ------------------------------------------------------------------
# Повторяющиеся события (подмножество RRULE, ТЗ 4.3.2)
# ------------------------------------------------------------------

def parse_recurrence(rule: str):
    """Разбирает поддерживаемое подмножество RRULE.

    Поддерживается: 'daily', 'weekly', 'monthly', 'yearly',
    'weekly:BYDAY=MO,WE,FR', 'FREQ=DAILY;INTERVAL=3' и т.п.
    Возвращает dict или None, если правило неизвестно.
    """
    if not rule:
        return None
    base = rule.split(":", 1)
    params: dict[str, str] = {}
    freq = None
    if base[0] in {"daily", "weekly", "monthly", "yearly"}:
        freq = base[0].upper()
    elif base[0] == "weekly" and len(base) > 1:
        freq = "WEEKLY"
    for part in (base[1] if len(base) > 1 else base[0]).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip().upper()] = v.strip().upper()
    if freq is None and "FREQ" in params:
        freq = params["FREQ"]
    if freq not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        return None
    try:
        interval = max(1, int(params.get("INTERVAL", 1)))
    except ValueError:
        interval = 1
    byday = [d for d in params.get("BYDAY", "").split(",") if d in WEEKDAY_NAMES] or None
    eom = params.get("EOM") in {"1", "TRUE"}
    return {"freq": freq, "interval": interval, "byday": byday, "eom": eom}


def _occurrence_time(original: dt.datetime, day: dt.date) -> dt.datetime:
    naive = timezone.localtime(original)
    result = dt.datetime.combine(day, naive.time())
    return timezone.make_aware(result, naive.tzinfo)


def _day_in_month(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, cal.monthrange(year, month)[1]))


def _months_between(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _occurrence_at(rule_date: int, rule: dict, start_date: dt.date) -> dt.date | None:
    """Дата rule_date-го вхождения для MONTHLY/YEARLY (0 = self start_date)."""
    if rule["freq"] == "MONTHLY":
        total = start_date.month - 1 + rule_date * rule["interval"]
        year, month = start_date.year + total // 12, total % 12 + 1
        if rule.get("eom"):
            return dt.date(year, month, cal.monthrange(year, month)[1])
        return _day_in_month(year, month, start_date.day)
    if rule["freq"] == "YEARLY":
        year = start_date.year + rule_date * rule["interval"]
        try:
            return start_date.replace(year=year)
        except ValueError:  # 29 февраля
            return start_date.replace(year=year, day=28)
    return None


def expand_recurring(event: Event, range_start: dt.date, range_end: dt.date) -> list[dt.datetime]:
    """Даты начала экземпляров повторяющегося события в окне [range_start, range_end].

    Первый экземпляр — оригинальная дата start_at; далее — по правилу,
    с ограничением recurrence_end и recurrence_count. Окно итерации
    стартует арифметически от range_start (не от даты создания), лимит
    считается по всем вхождениям от start_at.
    """
    rule = parse_recurrence(event.recurrence_rule)
    if not rule or event.start_at is None:
        return []
    start_dt = event.start_at
    start_date = timezone.localtime(start_dt).date()
    max_dt = None
    if event.recurrence_end:
        max_dt = timezone.localtime(event.recurrence_end).date()
    count_limit = event.recurrence_count or 0
    window_end = range_end if max_dt is None else min(range_end, max_dt)
    if window_end < range_start or window_end < start_date:
        return []

    freq = rule["freq"]
    interval = rule["interval"]

    # Арифметический якорь: индекс первого вхождения >= range_start и число до окна
    if freq == "DAILY":
        if range_start <= start_date:
            k0 = 0
        else:
            k0 = -(-(range_start - start_date).days // interval)
        before = k0
    elif freq == "WEEKLY" and not rule["byday"]:
        if range_start <= start_date:
            k0 = 0
        else:
            k0 = -(-(range_start - start_date).days // (7 * interval))
        before = k0
    elif freq == "WEEKLY":  # byday: считаем вхождения до окна арифметикой по дням
        k0 = 0
        wanted = {WEEKDAY_NAMES.index(d) for d in rule["byday"]}
        if range_start > start_date:
            before = sum(
                1
                for offset in range((range_start - start_date).days)
                if (start_date + dt.timedelta(days=offset)).weekday() in wanted
            )
        else:
            before = 0
    elif freq in {"MONTHLY", "YEARLY"}:
        if range_start <= start_date:
            k0 = 0
        else:
            unit = _months_between if freq == "MONTHLY" else lambda a, b: b.year - a.year
            k0 = max(0, -(-unit(start_date, range_start) // interval))
            while (occ := _occurrence_at(k0, rule, start_date)) is not None and occ < range_start:
                k0 += 1
            if occ is None:
                return []
        before = k0
    else:
        return []

    if count_limit and before >= count_limit:
        return []

    occurrences: list[dt.datetime] = []
    emitted = before
    cap = 1000

    def try_emit(day: dt.date):
        nonlocal emitted
        emitted += 1
        if count_limit and emitted > count_limit:
            return False
        if day > window_end:
            return False
        if day >= range_start:
            occurrences.append(_occurrence_time(start_dt, day))
        return True

    if freq == "DAILY":
        day = start_date + dt.timedelta(days=k0 * interval)
        while day <= window_end and emitted - before < cap:
            if not try_emit(day):
                break
            day += dt.timedelta(days=interval)
    elif freq == "WEEKLY" and not rule["byday"]:
        day = start_date + dt.timedelta(weeks=k0 * interval)
        while day <= window_end and emitted - before < cap:
            if not try_emit(day):
                break
            day += dt.timedelta(weeks=interval)
    elif freq == "WEEKLY":  # byday — проход только по дням окна
        wanted = {WEEKDAY_NAMES.index(d) for d in rule["byday"]}
        day = max(range_start, start_date)
        while day <= window_end and emitted - before < cap:
            if day.weekday() in wanted:
                if not try_emit(day):
                    break
            day += dt.timedelta(days=1)
    else:  # MONTHLY / YEARLY
        k = k0
        while emitted - before < cap:
            day = _occurrence_at(k, rule, start_date)
            if day is None or day > window_end:
                break
            if not try_emit(day):
                break
            k += 1
    return occurrences


def events_for_range(user, scope_code: str, range_start: dt.date, range_end: dt.date) -> list[dict]:
    """Экземпляры событий в окне дат: обычные + развёрнутые повторы.

    Возвращает список {'event': Event, 'start': datetime, 'recurring': bool},
    отсортированный по дате начала. Обычные события фильтруются на уровне БД
    по окну (индекс start_at), повторы — по совместимости с концом окна.
    """
    from django.db.models import Q

    tz = timezone.get_current_timezone()
    win_start = timezone.make_aware(dt.datetime.combine(range_start, dt.time.min), tz)
    win_end = timezone.make_aware(dt.datetime.combine(range_end, dt.time.max), tz)

    result: list[dict] = []
    base = owned_queryset(Event, user, scope__code=scope_code, start_at__isnull=False)
    for ev in base.filter(recurrence_rule="").filter(start_at__gte=win_start, start_at__lte=win_end).select_related("project", "status"):
        result.append({"event": ev, "start": ev.start_at, "recurring": False})
    recurring = base.exclude(recurrence_rule="").filter(
        Q(recurrence_end__isnull=True) | Q(recurrence_end__gte=win_start)
    ).select_related("project", "status")[:500]
    for ev in recurring:
        for occ in expand_recurring(ev, range_start, range_end):
            result.append({"event": ev, "start": occ, "recurring": True})
    result.sort(key=lambda x: x["start"])
    return result


def upcoming_events(user, scope_code: str, limit: int = 5) -> list[dict]:
    """Ближайшие (ещё не наступившие) события личного раздела с учётом повторов."""
    now = timezone.now()
    horizon = (now + dt.timedelta(days=90)).date()
    items = events_for_range(user, scope_code, timezone.localdate(), horizon)
    return [x for x in items if x["start"] >= now][:limit]


def create_comment(user, event: Event, text: str, files=()) -> Comment:
    """Комментарий + вложения (файлы уже провалидированы CommentForm)."""
    from .forms import detect_upload_type
    from .models import EventAttachment

    comment = Comment.objects.create(event=event, user=user, author=user, text=text)
    for f in files:
        EventAttachment.objects.create(
            event=event, comment=comment, user=user, file=f,
            mime_type=detect_upload_type(f) or "", size_bytes=f.size,
        )
    return comment
