from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.i18n import t
from apps.planner.models import Event, Project, Status
from apps.vehicles.models import Fine, FuelEntry, Insurance, Purchase, Service, Vehicle
from apps.vehicles.services import owned_queryset

DEFAULT_PERIOD = "6m"
PERIOD_CHOICES = ("3m", "6m", "12m", "all")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _months_back(end: date, months: int) -> date:
    total = end.year * 12 + (end.month - 1) - months
    year, month = divmod(total, 12)
    day = min(end.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def resolve_period(request) -> tuple[date | None, date | None, str]:
    """Окно отчёта по GET-параметрам period/start/end (ТЗ 11).

    period: 3m/6m/12m/all (по умолчанию 6m), custom — по start/end
    (dd.mm.yyyy или ISO). Невалидные значения откатываются к 6m.
    Возвращает (start, end, ключ периода); all → (None, None).
    """
    end = timezone.localdate()
    period = request.GET.get("period", DEFAULT_PERIOD)
    if period == "all":
        return None, None, "all"
    if period == "custom":
        start = _parse_date(request.GET.get("start"))
        custom_end = _parse_date(request.GET.get("end"))
        if start and custom_end and start > custom_end:
            start, custom_end = custom_end, start
        if start and custom_end:
            return start, custom_end, "custom"
        return _months_back(end, 6), end, DEFAULT_PERIOD
    months = {"3m": 3, "12m": 12}.get(period, 6)
    return _months_back(end, months), end, period if period in PERIOD_CHOICES else DEFAULT_PERIOD


# --- 6.2 Отчёты Бортжурнала (ТЗ 11.1 / 4.2.9) ---

ZERO = Decimal(0)


def user_vehicles(user, vehicle_id: str | None = None) -> list[Vehicle]:
    qs = owned_queryset(Vehicle, user).order_by("-is_default")
    if vehicle_id:
        qs = qs.filter(pk=vehicle_id)  # IDOR: чужое авто → пустой список
    return list(qs)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_index(key: str) -> int:
    year, month = key.split("-")
    return int(year) * 12 + int(month) - 1


def _month_label(key: str) -> str:
    return t(f"rep.month.{int(key[5:7])}")


def _window_months(start: date | None, end: date | None, records: list[date]) -> list[str]:
    """Список месяцев окна; при period=all — от самой ранней записи до сегодня."""
    end = end or timezone.localdate()
    if start is None:
        start = min(records) if records else end
    first = _month_index(_month_key(start))
    last = _month_index(_month_key(end))
    return [_month_key(date(idx // 12, idx % 12 + 1, 1)) for idx in range(first, last + 1)]


def _in_window(d: date | None, start: date | None, end: date) -> bool:
    return d is not None and (start is None or start <= d <= end)


def _fuel_station_name(entry: FuelEntry) -> str:
    if entry.station_id and entry.station:
        return entry.station.name
    return entry.station_custom_name or t("rep.item.unnamed")


def vehicle_report_data(user, vehicles: list[Vehicle], start: date | None, end: date | None) -> dict:
    """Полный набор агрегатов отчёта Бортжурнала за окно по выбранным авто."""
    end = end or timezone.localdate()
    vehicle_ids = [v.pk for v in vehicles]
    fuel_rows = [
        e
        for e in FuelEntry.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False).select_related("station")
        if _in_window(e.fuel_date, start, end)
    ]
    purchase_rows = [
        p
        for p in Purchase.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False).select_related("category")
        if _in_window(p.purchase_date, start, end)
    ]
    service_rows = [
        s
        for s in Service.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False)
        if _in_window(s.service_date, start, end)
    ]
    fine_rows = [
        f
        for f in Fine.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False)
        if _in_window(f.fine_date, start, end)
    ]

    fuel_total = sum((e.total_cost or ZERO for e in fuel_rows), ZERO)
    liters = sum((e.volume_liters or ZERO for e in fuel_rows), ZERO)
    purchase_total = sum((p.amount or ZERO for p in purchase_rows), ZERO)
    service_total = sum((s.amount or ZERO for s in service_rows), ZERO)
    fine_total = sum((f.amount or ZERO for f in fine_rows), ZERO)
    other_total = purchase_total + service_total + fine_total
    total = fuel_total + other_total

    # Пробег в окне: размах одометра по всем источникам на каждое авто
    points: dict[object, list[int]] = {}
    for e in fuel_rows:
        points.setdefault(e.vehicle_id, []).append(e.odometer)
    for row in purchase_rows + service_rows:
        if row.odometer:
            points.setdefault(row.vehicle_id, []).append(row.odometer)
    mileage_km = sum(max(v) - min(v) for v in points.values() if len(v) >= 2)
    cost_per_km = (total / mileage_km).quantize(Decimal("0.01")) if mileage_km else None

    months = _window_months(start, end, [d for d in (
        [e.fuel_date for e in fuel_rows]
        + [p.purchase_date for p in purchase_rows]
        + [s.service_date for s in service_rows]
    ) if d])
    monthly = {key: {"month": key, "fuel": ZERO, "other": ZERO} for key in months}

    def bucket(d: date | None) -> dict | None:
        if d is None:
            return None
        return monthly.get(_month_key(d))

    for e in fuel_rows:
        row = bucket(e.fuel_date)
        if row:
            row["fuel"] += e.total_cost or ZERO
    for p in purchase_rows:
        row = bucket(p.purchase_date)
        if row:
            row["other"] += p.amount or ZERO
    for s in service_rows:
        row = bucket(s.service_date)
        if row:
            row["other"] += s.amount or ZERO
    for f in fine_rows:
        row = bucket(f.fine_date)
        if row:
            row["other"] += f.amount or ZERO
    monthly_list = []
    for key in months:
        row = monthly[key]
        row["total"] = row["fuel"] + row["other"]
        row["label"] = _month_label(key)
        monthly_list.append(row)

    # Категории (фиксированные статьи + категории покупок), по убыванию
    cats: dict[str, dict] = {}

    def add_cat(key: str, name: str, color: str, amount: Decimal) -> None:
        if not amount:
            return
        entry = cats.setdefault(key, {"key": key, "name": name, "color": color, "total": ZERO})
        entry["total"] += amount

    add_cat("fuel", t("vehicle.fuel"), "#3B82F6", fuel_total)
    for p in purchase_rows:
        name = p.category.name if p.category else t("rep.item.unnamed")
        color = (p.category.color if p.category else None) or "#10B981"
        add_cat(f"pur_{p.category_id or p.pk}", name, color, p.amount or ZERO)
    add_cat("service", t("vehicle.service"), "#8B5CF6", service_total)
    add_cat("fines", t("vehicle.fines"), "#EF4444", fine_total)
    categories = sorted(cats.values(), key=lambda c: c["total"], reverse=True)
    cat_max = categories[0]["total"] if categories else ZERO
    for c in categories:
        c["pct"] = int(c["total"] / total * 100) if total else 0
        c["bar_pct"] = int(c["total"] / cat_max * 100) if cat_max else 0

    # Топ-5 статей: покупки/сервисы записями, топливо — группами по АЗС
    items: list[dict] = []
    fuel_by_station: dict[str, Decimal] = {}
    for e in fuel_rows:
        fuel_by_station[_fuel_station_name(e)] = fuel_by_station.get(_fuel_station_name(e), ZERO) + (e.total_cost or ZERO)
    for name, amount in fuel_by_station.items():
        items.append({"name": name, "amount": amount, "meta": t("rep.source.fuel")})
    for p in purchase_rows:
        items.append({"name": p.title or t("rep.item.unnamed"), "amount": p.amount or ZERO, "meta": t("rep.source.purchase")})
    for s in service_rows:
        items.append({"name": s.service_station or t("rep.item.unnamed"), "amount": s.amount or ZERO, "meta": t("rep.source.service")})
    top = sorted((i for i in items if i["amount"]), key=lambda i: i["amount"], reverse=True)[:5]
    top_max = top[0]["amount"] if top else ZERO
    for item in top:
        item["bar_pct"] = int(item["amount"] / top_max * 100) if top_max else 0

    # Расход л/100: интервалы между полными баками (полная история в окне)
    consumption_by_month: dict[str, list[float]] = {}
    total_interval_liters = ZERO
    total_interval_km = 0
    avg_consumption = None
    for vehicle in vehicles:
        entries = sorted(
            (e for e in fuel_rows if e.vehicle_id == vehicle.pk and e.full_tank and e.volume_liters),
            key=lambda e: (e.fuel_date, e.odometer),
        )
        prev_odo = None
        for e in entries:
            if prev_odo is not None and e.odometer > prev_odo:
                km = e.odometer - prev_odo
                key = _month_key(e.fuel_date)
                consumption_by_month.setdefault(key, []).append(float(e.volume_liters) / km * 100)
                total_interval_liters += e.volume_liters
                total_interval_km += km
            prev_odo = e.odometer
    if total_interval_km:
        avg_consumption = (total_interval_liters / total_interval_km * 100).quantize(Decimal("0.1"))
    consumption = []
    for key in months:
        values = consumption_by_month.get(key, [])
        consumption.append({
            "month": key,
            "label": _month_label(key),
            "value": round(sum(values) / len(values), 1) if values else None,
        })

    # Сводка страховки/штрафов (ТЗ 11.1) — активные полисы и штрафы
    today = timezone.localdate()
    insurance_rows = Insurance.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False)
    active = [i for i in insurance_rows if i.end_date and i.end_date >= today]
    unpaid = [f for f in Fine.objects.filter(vehicle_id__in=vehicle_ids, is_deleted=False, status="unpaid")]
    paid_in_window = [f for f in fine_rows if f.status == "paid"]
    summary = {
        "insurance_active": len(active),
        "insurance_yearly": sum((i.cost or ZERO for i in active), ZERO),
        "fines_unpaid_count": len(unpaid),
        "fines_unpaid_sum": sum((f.amount or ZERO for f in unpaid), ZERO),
        "fines_paid_count": len(paid_in_window),
        "fines_paid_sum": sum((f.amount or ZERO for f in paid_in_window), ZERO),
    }

    return {
        "kpi": {
            "total": total,
            "fuel": fuel_total,
            "other": other_total,
            "liters": liters,
            "mileage_km": mileage_km,
            "cost_per_km": cost_per_km,
            "avg_consumption": avg_consumption,
        },
        "monthly": monthly_list,
        "categories": categories,
        "top": top,
        "consumption": consumption,
        "summary": summary,
        "months": len(months),
    }


def service_forecast(user, vehicles: list[Vehicle]) -> dict | None:
    """Прогноз следующего ТО (ТЗ 11.1) по средним интервалам истории сервисов.

    Только для одного выбранного авто; нужно минимум 2 сервиса с одометром.
    """
    if len(vehicles) != 1:
        return None
    vehicle = vehicles[0]
    svcs = [
        s
        for s in Service.objects.filter(vehicle=vehicle, is_deleted=False)
        .exclude(odometer__isnull=True)
        .order_by("service_date")
        if s.service_date
    ]
    if len(svcs) < 2:
        return None
    first, last = svcs[0], svcs[-1]
    spans = len(svcs) - 1
    avg_km = (last.odometer - first.odometer) / spans if last.odometer > first.odometer else None
    days_span = (last.service_date - first.service_date).days
    avg_days = days_span / spans if days_span > 0 else None

    today = timezone.localdate()
    current = max(vehicle.current_mileage or 0, last.odometer)
    km_left = max(int(avg_km - (current - last.odometer)), 0) if avg_km else None
    next_date = last.service_date + timedelta(days=int(avg_days)) if avg_days else None
    days_left = (next_date - today).days if next_date else None

    from apps.vehicles.models import PlannedEvent

    planned = (
        PlannedEvent.objects.filter(vehicle=vehicle, is_deleted=False, is_done=False)
        .exclude(planned_date__isnull=True)
        .order_by("planned_date")
        .first()
    )
    return {
        "last_service_date": last.service_date,
        "last_odometer": last.odometer,
        "avg_km": round(avg_km) if avg_km else None,
        "avg_days": int(avg_days) if avg_days else None,
        "current": current,
        "next_km": int(last.odometer + avg_km) if avg_km else None,
        "km_left": km_left,
        "next_date": next_date,
        "days_left": days_left,
        "planned": planned,
    }


# --- 6.3 Отчёты Записной книжки (ТЗ 11.2 / 4.3.6) ---

SECONDS_PER_DAY = 86400.0


def _window_datetimes(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    end = end or timezone.localdate()
    start_dt = timezone.make_aware(datetime.combine(start or date.min, datetime.min.time()), tz)
    end_dt = timezone.make_aware(datetime.combine(end, datetime.max.time()), tz)
    return start_dt, end_dt


def _status_at(hist: list, at: datetime, fallback):
    """Статус задачи на момент `at` по истории смен (hist отсортирована по changed_at)."""
    last = None
    for h in hist:
        if h.changed_at <= at:
            last = h
        else:
            break
    if last is not None:
        return last.to_status_id
    if hist:
        return hist[0].from_status_id
    return fallback


def planner_report_data(user, scope_code: str, start: date | None, end: date) -> dict:
    """Полный набор агрегатов рабочего/личного отчёта за окно (ТЗ 11.2)."""
    start_dt, end_dt = _window_datetimes(start, end)
    now = timezone.now()
    events = list(
        Event.objects.filter(user=user, scope__code=scope_code, is_deleted=False).select_related(
            "status", "project"
        ).prefetch_related("status_history")
    )
    statuses = {s.pk: s for s in owned_queryset(Status, user)}
    for s in Status.objects.filter(user__isnull=True, is_system=True):
        statuses.setdefault(s.pk, s)

    def hist_of(event) -> list:
        return sorted(event.status_history.all(), key=lambda h: h.changed_at)

    def in_window(dt: datetime | None) -> bool:
        return dt is not None and start_dt <= dt <= end_dt

    active = []  # задачи с активностью в окне
    histories: dict = {}
    for e in events:
        h = hist_of(e)
        histories[e.pk] = h
        touched = in_window(e.created_at) or in_window(e.completed_at) or any(
            in_window(x.changed_at) for x in h
        )
        if touched:
            active.append(e)

    # 1. Количество задач по статусам за период — статус на конец окна
    ref = min(end_dt, now)
    status_counts: dict[object, int] = {}
    for e in active:
        sid = _status_at(histories[e.pk], ref, e.status_id)
        status_counts[sid] = status_counts.get(sid, 0) + 1

    def status_row(sid):
        st = statuses.get(sid)
        return {
            "name": st.name if st else t("rep.status_none"),
            "color": st.color if st else "#94A3B8",
        }

    by_status = sorted(
        ({**status_row(sid), "count": n} for sid, n in status_counts.items()),
        key=lambda row: -row["count"],
    )

    # 2. Среднее время нахождения в статусе (сегменты, начатые в окне)
    durations: dict[object, list[float]] = {}
    cycles: list[float] = []
    for e in active:
        segs: list[tuple] = []
        h = histories[e.pk]
        if h:
            segs.append((h[0].from_status_id, e.created_at, h[0].changed_at))
            for i, change in enumerate(h):
                nxt = h[i + 1].changed_at if i + 1 < len(h) else None
                segs.append((change.to_status_id, change.changed_at, nxt))
        else:
            segs.append((e.status_id, e.created_at, None))
        for sid, seg_start, seg_end in segs:
            if not start_dt <= seg_start <= end_dt:
                continue
            finish = seg_end or (now if seg_start <= now else None)
            if finish is None:
                continue
            durations.setdefault(sid, []).append((finish - seg_start).total_seconds() / SECONDS_PER_DAY)
        if e.completed_at and in_window(e.completed_at):
            cycles.append((e.completed_at - e.created_at).total_seconds() / SECONDS_PER_DAY)
    avg_status = [
        {**status_row(sid), "days": round(sum(v) / len(v), 1)}
        for sid, v in durations.items()
    ]
    avg_status.sort(key=lambda row: -row["days"])
    days_max = max((row["days"] for row in avg_status), default=0) or 1
    for row in avg_status:
        row["bar_pct"] = int(row["days"] / days_max * 100)
    avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else None

    # 3. Выполнено vs просрочено
    done_on_time = done_late = overdue_open = 0
    for e in active:
        if e.completed_at and in_window(e.completed_at):
            if e.due_at and e.completed_at > e.due_at:
                done_late += 1
            else:
                done_on_time += 1
        elif not e.completed_at and e.due_at and e.due_at < min(end_dt, now):
            overdue_open += 1
    done_total = done_on_time + done_late
    on_time_pct = int(done_on_time / done_total * 100) if done_total else 0

    # 4. Производительность по ISO-неделям: создано / закрыто
    weeks: dict[str, dict] = {}

    def week_key(d: datetime) -> str:
        iso = d.isocalendar()
        return f"{iso[0]}-{iso[1]:02d}"

    def week_label(d: datetime) -> str:
        iso = d.isocalendar()
        return t("rep.week", week=iso[1])

    for e in active:
        if in_window(e.created_at):
            w = weeks.setdefault(week_key(e.created_at), {"week": week_key(e.created_at), "label": week_label(e.created_at), "created": 0, "closed": 0})
            w["created"] += 1
        if e.completed_at and in_window(e.completed_at):
            w = weeks.setdefault(week_key(e.completed_at), {"week": week_key(e.completed_at), "label": week_label(e.completed_at), "created": 0, "closed": 0})
            w["closed"] += 1
    weekly = sorted(weeks.values(), key=lambda row: row["week"])

    # Факт/оценка часов по завершённым в окне
    done_rows = [e for e in active if e.completed_at and in_window(e.completed_at)]
    hours_fact = round(sum(e.actual_minutes or 0 for e in done_rows) / 60, 1)
    hours_est = round(sum(e.estimated_minutes or 0 for e in done_rows) / 60, 1)

    return {
        "kpi": {
            "total": len(active),
            "done": done_total,
            "overdue": overdue_open,
            "avg_cycle": avg_cycle,
            "hours_fact": hours_fact,
            "hours_est": hours_est,
        },
        "by_status": by_status,
        "avg_status": avg_status,
        "on_time": {"done_on_time": done_on_time, "done_late": done_late, "overdue_open": overdue_open, "pct": on_time_pct},
        "weekly": weekly,
    }


def planner_burndown(user, scope_code: str, start: date | None, end: date, project_id: str | None = None) -> dict | None:
    """Burndown по проекту (ТЗ 11.2): недельные точки остатка открытых задач + идеальная линия.

    project_id — конкретный проект (или None: первый проект со задачами).
    """
    start_dt, end_dt = _window_datetimes(start, end)
    projects = owned_queryset(Project, user).filter(scope__code=scope_code)
    if project_id:
        projects = projects.filter(pk=project_id)
    project = None
    if project_id:
        project = projects.order_by("created_at").first()
        if project is None:
            return None
    else:
        for p in projects.order_by("created_at"):
            if Event.objects.filter(user=user, project=p, is_deleted=False).exists():
                project = p
                break
    if project is None:
        return None
    events = list(
        Event.objects.filter(user=user, project=project, is_deleted=False).exclude(created_at__gt=end_dt)
    )
    if not events:
        return None
    anchor = max(start_dt, min(e.created_at for e in events))
    dates: list[datetime] = []
    d = anchor
    while d <= end_dt and len(dates) < 60:
        dates.append(d)
        d += timedelta(days=7)
    if dates[-1] < end_dt:
        dates.append(end_dt)

    def remaining_at(at: datetime) -> int:
        return sum(1 for e in events if e.created_at <= at and (not e.completed_at or e.completed_at > at))

    first_remaining = remaining_at(dates[0])
    last = len(dates) - 1
    points = [
        {
            "label": at.strftime("%d.%m"),
            "remaining": remaining_at(at),
            "ideal": round(first_remaining * (1 - i / last), 1) if last else float(remaining_at(at)),
        }
        for i, at in enumerate(dates)
    ]
    return {"project_title": project.title, "project_color": project.color, "points": points}


def planner_top_longest(user, scope_code: str, start: date | None, end: date, limit: int = 5) -> list[dict]:
    """Топ-5 самых долгих задач (завершённых) за окно."""
    start_dt, end_dt = _window_datetimes(start, end)
    qs = (
        Event.objects.filter(
            user=user, scope__code=scope_code, is_deleted=False, completed_at__isnull=False,
            completed_at__gte=start_dt, completed_at__lte=end_dt,
        )
        .select_related("project")
    )
    rows = []
    for e in qs:
        days = (e.completed_at - e.created_at).total_seconds() / SECONDS_PER_DAY
        rows.append({
            "pk": e.pk,
            "title": e.title,
            "project": e.project.title if e.project else None,
            "days": round(days, 1),
        })
    rows.sort(key=lambda r: -r["days"])
    return rows[:limit]
