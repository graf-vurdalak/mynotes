"""Celery-задачи напоминаний и уведомлений (ТЗ 4.2.8/4.3.5, план Этапа 5).

Источники истины — сканы по расписанию Beat, а не сигналы записи: напоминание
«за N минут до события» требует отложенной проверки. Идемпотентность обеспечивают
флаги сущностей (``reminder_sent`` / ``last_reminder_at`` / ``reminder_created``).
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.i18n import t
from apps.planner.models import Event, Scope
from apps.planner.services import expand_recurring, get_scope

from .services import notify

logger = logging.getLogger(__name__)

LOOKAHEAD_DAYS = 7


def _effective_minutes(event: Event) -> int | None:
    """Порог напоминания в минутах: индивидуальный ?? глобальный; None/0 — выкл."""
    if event.reminder_minutes_before is not None:
        minutes = event.reminder_minutes_before
    else:
        user_settings = getattr(event.user, "settings", None)
        minutes = user_settings.reminder_default_minutes if user_settings else None
    return minutes if minutes and minutes > 0 else None


def _fire_event_reminder(event: Event, when, minutes: int) -> None:
    title = t("notif.event.title", title=event.title)
    body = t(
        "notif.event.body",
        title=event.title,
        when=timezone.localtime(when).strftime("%d.%m.%Y %H:%M"),
        minutes=minutes,
    )
    notify(
        event.user, "planner.event_reminder", title, body,
        entity=event, channels=("email", "telegram"), bot="planner",
    )


@shared_task(name="notifications.scan_event_reminders")
def scan_event_reminders() -> int:
    """Напоминания Записной книжки (ТЗ 4.3.5): ближайшие экземпляры событий."""
    now = timezone.now()
    fired = 0

    horizon = now + timedelta(days=LOOKAHEAD_DAYS)
    plain = Event.objects.filter(
        is_deleted=False,
        reminder_sent=False,
        recurrence_rule="",
        start_at__gt=now,
        start_at__lte=horizon,
    ).select_related("user", "user__settings")
    for event in plain:
        minutes = _effective_minutes(event)
        if minutes is None or event.start_at > now + timedelta(minutes=minutes):
            continue
        _fire_event_reminder(event, event.start_at, minutes)
        event.reminder_sent = True
        event.save(update_fields=["reminder_sent", "updated_at"])
        fired += 1

    recurring = Event.objects.filter(
        is_deleted=False,
        start_at__gt=now - timedelta(days=400),
    ).exclude(recurrence_rule="").select_related("user", "user__settings")
    for event in recurring:
        minutes = _effective_minutes(event)
        if minutes is None:
            continue
        window_end = now + timedelta(days=LOOKAHEAD_DAYS, minutes=minutes)
        occurrences = [o for o in expand_recurring(event, now.date(), window_end.date()) if o > now]
        if not occurrences:
            continue
        occurrence = occurrences[0]
        if event.last_reminder_at and event.last_reminder_at >= occurrence:
            continue
        if occurrence > now + timedelta(minutes=minutes):
            continue
        _fire_event_reminder(event, occurrence, minutes)
        event.last_reminder_at = occurrence
        event.save(update_fields=["last_reminder_at", "updated_at"])
        fired += 1

    return fired


# --- Бортжурнал (ТЗ 4.2.8) -------------------------------------------------

@shared_task(name="notifications.scan_vehicle_reminders")
def scan_vehicle_reminders() -> int:
    fired = 0
    fired += _scan_insurances()
    fired += _scan_planned()
    fired += _scan_fines()
    fired += _scan_transport_tax()
    return fired


def _fmt_date(d) -> str:
    return d.strftime("%d.%m.%Y")


def _scan_insurances() -> int:
    """Страховки, истекающие в пределах insurance_reminder_days (ТЗ 4.2.6/4.2.8).

    Уведомление + авто-событие в «Личное» (флаг ``reminder_created`` ставится
    один раз, чтобы перескан не плодил события).
    """
    from apps.vehicles.models import Insurance

    today = timezone.localdate()
    fired = 0
    insurances = Insurance.objects.filter(
        is_deleted=False, reminder_created=False, end_date__isnull=False, end_date__gte=today
    ).select_related("user", "vehicle")
    for ins in insurances:
        lead = getattr(ins.user.settings, "insurance_reminder_days", 30) if hasattr(ins.user, "settings") else 30
        days_left = (ins.end_date - today).days
        if days_left > lead:
            continue
        title = t("notif.insurance.title", days=days_left)
        body = t("notif.insurance.body", company=ins.company or "—",
                 number=ins.policy_number or "—", when=_fmt_date(ins.end_date))
        notify(ins.user, "insurance.expiring", title, body, entity=ins,
               channels=("email", "telegram"), bot="vehicle")
        try:
            scope = get_scope(ins.user, Scope.PERSONAL)
            Event.objects.create(
                user=ins.user, scope=scope,
                title=t("notif.insurance.event", when=_fmt_date(ins.end_date)),
                event_type="reminder",
                start_at=timezone.make_aware(datetime.combine(ins.end_date, time(0, 0))),
            )
        except Exception:
            logger.exception("Авто-событие для страховки %s не создано", ins.pk)
        ins.reminder_created = True
        ins.save(update_fields=["reminder_created", "updated_at"])
        fired += 1
    return fired


def _scan_planned() -> int:
    """Плановые работы: по дате (за N дней) и/или по пробегу (ТЗ 4.2.8)."""
    from apps.vehicles.models import PlannedEvent

    now = timezone.now()
    fired = 0
    events = PlannedEvent.objects.filter(
        is_deleted=False, is_done=False
    ).select_related("user", "vehicle")
    for pe in events:
        lead = getattr(pe.user.settings, "plan_reminder_days", 7) if hasattr(pe.user, "settings") else 7
        reason = None
        if pe.reminder_type in ("date", "both") and pe.planned_date:
            if now <= pe.planned_date <= now + timedelta(days=lead):
                reason = t("notif.plan.date", when=timezone.localtime(pe.planned_date).strftime("%d.%m.%Y %H:%M"))
        if reason is None and pe.reminder_type in ("mileage", "both") and pe.reminder_mileage:
            current = pe.vehicle.current_mileage or 0
            if current >= pe.reminder_mileage:
                reason = t("notif.plan.mileage", target=pe.reminder_mileage, current=current)
        if reason is None:
            continue
        title = t("notif.plan.title")
        body = t("notif.plan.body", desc=(pe.description or "—"), reason=reason)
        n = notify(pe.user, "vehicle.planned_due", title, body, entity=pe,
                   channels=("email", "telegram"), bot="vehicle",
                   dedup_within=timedelta(days=1))
        if n is not None:
            fired += 1
    return fired


def _scan_fines() -> int:
    """Дайджест неоплаченных штрафов: не чаще одного раза в сутки (ТЗ 4.2.8)."""
    from apps.vehicles.models import Fine

    unpaid = Fine.objects.filter(is_deleted=False, status="unpaid").select_related("user")
    per_user: dict = {}
    for fine in unpaid:
        agg = per_user.setdefault(fine.user_id, {"user": fine.user, "count": 0, "amount": 0, "currency": "RUB"})
        agg["count"] += 1
        agg["amount"] += fine.amount or 0
        agg["currency"] = fine.currency_code or agg["currency"]
    fired = 0
    for agg in per_user.values():
        n = notify(agg["user"], "vehicle.fines_unpaid",
                   t("notif.fines.title", count=agg["count"]),
                   t("notif.fines.body", count=agg["count"], amount=f"{agg['amount']:.0f} {agg['currency']}"),
                   channels=("email", "telegram"), bot="vehicle",
                   dedup_within=timedelta(days=1))
        if n is not None:
            fired += 1
    return fired


def _scan_transport_tax() -> int:
    """Транспортный налог: раз в год на дату из UserSettings (ТЗ 4.2.8)."""
    from apps.accounts.models import UserSettings

    today = timezone.localdate()
    fired = 0
    for s in UserSettings.objects.filter(
        transport_tax_month=today.month, transport_tax_day=today.day
    ).select_related("user"):
        n = notify(s.user, "vehicle.transport_tax", t("notif.tax.title"), t("notif.tax.body"),
                   channels=("email", "telegram"), bot="vehicle",
                   dedup_within=timedelta(days=300))
        if n is not None:
            fired += 1
    return fired
