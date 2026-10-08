"""Бизнес-сервис-слой Бортжурнала.

Защита от IDOR: все выборки сущностей обязаны идти через ``owned_queryset`` /
``get_owned``, которые всегда фильтруют по владельцу (``user``) и исключают
soft-deleted записи (``is_deleted=False``).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Q
from django.utils import timezone

from apps.references.models import FuelStation

from .models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    PurchaseCategory,
    Service,
    Vehicle,
)

# Сущности, напрямую принадлежащие пользователю (имеют поле user + is_deleted).
OWNED_MODELS = (
    Vehicle,
    FuelEntry,
    Purchase,
    Service,
    Fine,
    Insurance,
    PlannedEvent,
)


def owned_queryset(model, user):
    """Возвращает выборку сущностей, принадлежащих пользователю и не удалённых."""
    if not model._meta.abstract and hasattr(model, "user"):
        return model.objects.filter(user=user, is_deleted=False)
    raise ValueError(f"{model} не является сущностью, принадлежащей пользователю")


def get_owned(model, user, pk):
    """Возвращает сущность по PK, проверяя принадлежность пользователю.

    Возбуждает ``model.DoesNotExist`` при отсутствии/чужой/удалённой записи.
    """
    return owned_queryset(model, user).get(pk=pk)


def vehicle_belongs_to_user(vehicle, user) -> bool:
    return vehicle.user_id == user.id and not vehicle.is_deleted


def set_default_vehicle(user, vehicle) -> Vehicle:
    """Назначает авто «по умолчанию», снимая флаг с остальных авто пользователя."""
    Vehicle.objects.filter(user=user, is_deleted=False).exclude(pk=vehicle.pk).update(
        is_default=False
    )
    if not vehicle.is_default:
        Vehicle.objects.filter(pk=vehicle.pk).update(is_default=True)
    return vehicle


def get_latest_odometer(vehicle_id: int | str):
    """Максимальный одометр по свежим записям (заправки/сервис/покупки)."""
    best = 0
    for model in (FuelEntry, Service, Purchase):
        value = (
            model.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
            .order_by("-odometer")
            .values_list("odometer", flat=True)
            .first()
        )
        if value and value > best:
            best = value
    return best


def recalc_vehicle_mileage(vehicle) -> Vehicle:
    """Пересчитывает current_mileage авто по максимальному одометру записей."""
    if isinstance(vehicle, (int, str)):
        vehicle = Vehicle.objects.get(pk=vehicle)
    latest = get_latest_odometer(vehicle.pk)
    if latest != vehicle.current_mileage:
        vehicle.current_mileage = latest or vehicle.current_mileage or 0
        Vehicle.objects.filter(pk=vehicle.pk).update(
            current_mileage=vehicle.current_mileage, updated_at=vehicle.updated_at
        )
    return vehicle


def recalc_fuel_entry_totals(entry: FuelEntry, commit: bool = True) -> FuelEntry:
    """Авто-расчёт total_cost = volume_liters × price_per_liter."""
    if entry.volume_liters is not None and entry.price_per_liter is not None:
        entry.total_cost = (
            entry.volume_liters * entry.price_per_liter
        ).quantize(Decimal("0.01"))
        if commit:
            entry.save(update_fields=["total_cost", "updated_at"])
    return entry


def resolve_fuel_station(entry: FuelEntry, user) -> FuelEntry:
    """Устанавливает АЗС: выбранная из справочника или произвольная запись.

    Если заполнено ``station_custom_name`` и не выбрана станция из каталога,
    создаёт пользовательскую FuelStation, чтобы она появилась в «недавних».
    """
    name = (entry.station_custom_name or "").strip()
    if not entry.station and name:
        station = FuelStation.objects.filter(
            Q(is_system=True) | Q(created_by=user), name__iexact=name
        ).first()
        if station is None:
            station = FuelStation.objects.create(name=name, created_by=user)
        entry.station = station
        entry.station_custom_name = ""
    return entry


def compute_fuel_consumption(entry: FuelEntry, prev: FuelEntry | None = None) -> Decimal | None:
    """Расход по заправке, л/100 км, по полному баку относительно предыдущей.

    Учитываем только записи с полным баком и известным пробегом/объёмом.
    """
    if (
        not entry.full_tank
        or entry.volume_liters is None
        or entry.odometer is None
    ):
        return None
    if prev is None:
        prev = FuelEntry.objects.filter(
            vehicle_id=entry.vehicle_id,
            is_deleted=False,
            full_tank=True,
            odometer__lt=entry.odometer,
        ).order_by("-odometer").first()
    if prev is None or prev.odometer is None:
        return None
    distance = entry.odometer - prev.odometer
    if distance <= 0:
        return None
    return (entry.volume_liters / distance * 100).quantize(Decimal("0.1"))


def attach_consumption(entries) -> list[FuelEntry]:
    """Присваивает каждой заправке атрибут ``consumption`` (л/100 км)."""
    ordered = sorted(entries, key=lambda e: (e.odometer or 0, e.fuel_date))
    prev = None
    for entry in ordered:
        entry.consumption = compute_fuel_consumption(entry, prev)
        if entry.full_tank:
            prev = entry
    return entries


def fuel_summary(vehicle_id, since=None) -> dict:
    """Агрегаты по заправкам: сумма, литры, ср. цена, ср. расход, цена за км."""
    qs = FuelEntry.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    if since is not None:
        qs = qs.filter(fuel_date__gte=since)
    entries = list(qs)

    total_cost = sum((e.total_cost or 0) for e in entries)
    total_liters = sum((e.volume_liters or 0) for e in entries)
    priced = [e for e in entries if e.price_per_liter is not None]
    avg_price = (
        (sum(e.price_per_liter for e in priced) / len(priced)).quantize(Decimal("0.01"))
        if priced
        else None
    )

    full = sorted(
        (e for e in entries if e.full_tank and e.volume_liters and e.odometer),
        key=lambda e: e.odometer,
    )
    prev = None
    total_distance = 0
    liters = Decimal(0)
    for e in full:
        if prev is not None and e.odometer > prev.odometer:
            total_distance += e.odometer - prev.odometer
            liters += e.volume_liters
        prev = e

    avg_consumption = (
        (liters / total_distance * 100).quantize(Decimal("0.1"))
        if total_distance > 0
        else None
    )
    cost_per_km = (
        (total_cost / total_distance).quantize(Decimal("0.01"))
        if total_distance > 0
        else None
    )

    return {
        "total_cost": total_cost,
        "total_liters": total_liters,
        "avg_price": avg_price,
        "avg_consumption": avg_consumption,
        "cost_per_km": cost_per_km,
    }


def consumption_history(vehicle_id, months: int = 6) -> list[dict]:
    """Помесячный средний расход (л/100 км) для графика."""
    entries = list(
        FuelEntry.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    )
    attach_consumption(entries)
    by_month: dict[str, list[float]] = {}
    for e in entries:
        if e.consumption is not None:
            by_month.setdefault(e.fuel_date.strftime("%Y-%m"), []).append(
                float(e.consumption)
            )
    out = []
    for key in sorted(by_month.keys())[-months:]:
        values = by_month[key]
        out.append({"month": key, "consumption": round(sum(values) / len(values), 1)})
    return out


def recent_fuel_stations(user, limit: int = 6) -> list[FuelStation]:
    """Недавние АЗС пользователя для подсказок формы (по дате заправок)."""
    ids = (
        FuelEntry.objects.filter(vehicle__user=user, is_deleted=False)
        .exclude(station__isnull=True)
        .values("station_id")
        .annotate(latest=Max("fuel_date"))
        .order_by("-latest")
        .values_list("station_id", flat=True)[:limit]
    )
    stations = FuelStation.objects.filter(id__in=list(ids))
    return list(stations)


def purchase_summary(vehicle_id, since=None) -> dict:
    """Агрегаты по покупкам: сумма и разбивка по категориям за период."""
    qs = Purchase.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    if since is not None:
        qs = qs.filter(purchase_date__gte=since)
    purchases = list(qs.select_related("category"))

    total = sum((p.amount or 0) for p in purchases)
    by_category: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for p in purchases:
        by_category[p.category_id or "none"] += p.amount or 0

    categories = []
    for purchase in purchases:
        if purchase.category and purchase.category_id not in {
            c["id"] for c in categories
        }:
            categories.append(
                {
                    "id": str(purchase.category_id),
                    "name": purchase.category.name,
                    "color": purchase.category.color or "#2563EB",
                    "total": by_category[purchase.category_id],
                }
            )
    return {
        "total": total,
        "count": len(purchases),
        "by_category": categories,
    }


def service_summary(vehicle_id, year=None) -> dict:
    """Агрегаты по сервису: сумма за период и последние работы."""
    qs = Service.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    if year is not None:
        qs = qs.filter(service_date__year=year)
    items = list(qs)
    return {
        "total": sum((s.amount or 0) for s in items),
        "count": len(items),
        "items": items[:5],
    }


def fine_summary(vehicle_id, year=None) -> dict:
    """Агрегаты по штрафам: не оплачено, оплачено и всего за период."""
    qs = Fine.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    if year is not None:
        qs = qs.filter(fine_date__year=year)
    fines = list(qs)
    return {
        "total": sum((f.amount or 0) for f in fines),
        "unpaid": sum((f.amount or 0) for f in fines if f.status == "unpaid"),
        "paid": sum((f.amount or 0) for f in fines if f.status == "paid"),
        "count": len(fines),
    }


def insurance_summary(vehicle_id) -> dict:
    """Агрегаты по страховкам: активные, истекающие скоро, просроченные и стоимость."""
    qs = Insurance.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    insurances = list(qs)
    today = timezone.now().date()
    deadline = today + timedelta(days=30)
    active = [
        i for i in insurances if i.end_date and i.end_date >= today
    ]
    expiring = [
        i
        for i in insurances
        if i.end_date and today <= i.end_date <= deadline
    ]
    expired = [i for i in insurances if i.end_date and i.end_date < today]
    return {
        "count": len(insurances),
        "active": len(active),
        "expiring": len(expiring),
        "expired": len(expired),
        "yearly": sum((i.cost or 0) for i in active),
        "total": sum((i.cost or 0) for i in insurances),
    }


def sync_fine_purchase(fine: Fine, user, link: bool) -> Fine:
    """Синхронизирует связь штрафа с записью в «Покупках» (категория «Штрафы»).

    При ``link=True`` и оплаченном штрафе создаёт/обновляет запись покупки и
    привязывает её к штрафу. Иначе (не отмечено / не оплачен) — отвязывает
    запись и soft-удаляет её, если она больше ни к чему не привязана.
    """
    if not (link and fine.status == "paid"):
        if fine.purchase_id:
            purchase = fine.purchase
            fine.purchase = None
            Fine.objects.filter(pk=fine.pk).update(
                purchase_id=None, updated_at=fine.updated_at
            )
            if not purchase.fines.exclude(pk=fine.pk).exists():
                purchase.delete()
        return fine

    title = (
        (fine.description or "").strip()
        or (fine.decision_number or "").strip()
        or "Штраф"
    )
    category = PurchaseCategory.objects.filter(
        Q(user__isnull=True) | Q(user=user), name__iexact="Штрафы"
    ).first()
    pdate = fine.paid_at or fine.fine_date or timezone.now().date()

    if fine.purchase_id:
        purchase = fine.purchase
        changed = False
        if purchase.title != title:
            purchase.title = title
            changed = True
        if purchase.amount != fine.amount:
            purchase.amount = fine.amount
            changed = True
        if purchase.purchase_date != pdate:
            purchase.purchase_date = pdate
            changed = True
        if purchase.vehicle_id != fine.vehicle_id:
            purchase.vehicle = fine.vehicle
            changed = True
        if category and purchase.category_id != category.id:
            purchase.category = category
            changed = True
        if changed:
            purchase.save()
    else:
        purchase = Purchase.objects.create(
            user=user,
            vehicle=fine.vehicle,
            category=category,
            title=title,
            amount=fine.amount,
            purchase_date=pdate,
        )
        Fine.objects.filter(pk=fine.pk).update(purchase=purchase)
    return fine


def attach_plan_context(events, current_mileage=None) -> list:
    """Добавляет событиям атрибуты для карточек: km_left (по пробегу) и days_left (по дате)."""
    current = current_mileage or 0
    today = timezone.now().date()
    for e in events:
        e.km_left = None
        e.days_left = None
        if e.reminder_type == "mileage" and e.reminder_mileage is not None:
            e.km_left = e.reminder_mileage - current
        if e.planned_date:
            e.days_left = (e.planned_date.date() - today).days
    return events


def planned_summary(vehicle_id, current_mileage=None) -> dict:
    """Агрегаты по плановым событиям: бюджет и ближайшие.

    Возвращает сумму предполагаемых расходов и количество невыполненных
    событий, а также список ближайших (по дате, затем по целевому пробегу).
    """
    events = list(
        PlannedEvent.objects.filter(vehicle_id=vehicle_id, is_deleted=False)
    )
    pending = [e for e in events if not e.is_done]
    date_events = sorted(
        (e for e in pending if e.planned_date), key=lambda e: e.planned_date
    )
    mile_events = sorted(
        (e for e in pending if e.reminder_mileage is not None),
        key=lambda e: e.reminder_mileage,
    )
    attach_plan_context(pending, current_mileage)
    return {
        "count": len(events),
        "pending_count": len(pending),
        "budget": sum((e.estimated_cost or 0) for e in pending),
        "nearest": (date_events + mile_events)[:6],
    }


def monthly_cost(vehicle_id, months: int = 6) -> list[dict]:
    """Помесячные расходы (топливо/покупки/сервис/штрафы) для графика.

    Возвращает список от старых к новым месяцам, каждый с ключами
    ``month`` ("YYYY-MM"), ``fuel``, ``purchase``, ``service``, ``fines``
    и ``total``.
    """
    today = timezone.now().date()
    base = today.replace(day=1)

    def shift(count=0):
        idx = base.year * 12 + (base.month - 1) + count
        return idx // 12, idx % 12 + 1

    buckets = []
    for off in range(months):
        y, m = shift(off - months + 1)
        buckets.append(
            {
                "month": "%04d-%02d" % (y, m),
                "fuel": Decimal(0),
                "purchase": Decimal(0),
                "service": Decimal(0),
                "fines": Decimal(0),
                "total": Decimal(0),
            }
        )

    def bucket_index(date_value):
        if date_value is None:
            return None
        delta = (base.year - date_value.year) * 12 + (
            base.month - date_value.month
        )
        return (months - 1 - delta) if 0 <= delta < months else None

    def accumulate(kind, date_value, amount):
        i = bucket_index(date_value)
        if i is None:
            return
        amount = amount or Decimal(0)
        buckets[i][kind] += amount
        buckets[i]["total"] += amount

    for d, amt in FuelEntry.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("fuel_date", "total_cost"):
        accumulate("fuel", d, amt)
    for d, amt in Purchase.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("purchase_date", "amount"):
        accumulate("purchase", d, amt)
    for d, amt in Service.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("service_date", "amount"):
        accumulate("service", d, amt)
    for d, amt in Fine.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("fine_date", "amount"):
        accumulate("fines", d, amt)
    return buckets


def expenses_by_category(vehicle_id) -> list[dict]:
    """Статьи расходов (для круговой диаграммы и топ-5), по сумме.

    Фиксированные статьи помечаются ``key`` (fuel/service/insurance/fines),
    покупки — своим ``category_id`` и именем категории. Отсортированы по убыванию.
    """
    cats: dict[str, dict] = {}

    def add(key, name, color, amount):
        if not amount:
            return
        entry = cats.setdefault(
            key, {"key": key, "name": name, "color": color, "total": Decimal(0)}
        )
        entry["total"] += amount

    for amt in FuelEntry.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("total_cost", flat=True):
        add("fuel", "fuel", "#3B82F6", amt or Decimal(0))
    for p in Purchase.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).select_related("category"):
        if p.category:
            add(
                f"pur_{p.category_id}",
                p.category.name,
                p.category.color or "#10B981",
                p.amount or Decimal(0),
            )
        else:
            add(f"pur_{p.pk}", "", "#10B981", p.amount or Decimal(0))
    for samt in Service.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("amount", flat=True):
        add("service", "service", "#8B5CF6", samt or Decimal(0))
    for iamt in Insurance.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("cost", flat=True):
        add("insurance", "insurance", "#F59E0B", iamt or Decimal(0))
    for famt in Fine.objects.filter(
        vehicle_id=vehicle_id, is_deleted=False
    ).values_list("amount", flat=True):
        add("fines", "fines", "#EF4444", famt or Decimal(0))
    return sorted(cats.values(), key=lambda c: c["total"], reverse=True)


def dashboard_overview(user) -> dict:
    """Агрегаты дашборда /dashboard/ поверх всех авто пользователя.

    Возвращает данные для блока «Бортжурнал» (активное авто, расход/топливо
    за месяц, последние события) и блока уведомлений (истекающие страховки,
    неоплаченные штрафы, ближайшие плановые события).
    """
    now = timezone.now().date()
    month_start = now.replace(day=1)
    deadline = now + timedelta(days=30)

    vehicles = list(
        owned_queryset(Vehicle, user).select_related("brand", "model")
    )
    default = next((v for v in vehicles if v.is_default), None) or (
        vehicles[0] if vehicles else None
    )

    expenses_month = Decimal(0)
    fuel_month = Decimal(0)
    fuel_liters = Decimal(0)

    def accumulate(model, date_field, amount_field):
        values = list(
            model.objects.filter(
                user=user,
                is_deleted=False,
                **{f"{date_field}__gte": month_start},
            ).values_list(amount_field, flat=True)
        )
        return sum((v or Decimal(0) for v in values), Decimal(0))

    for liters in FuelEntry.objects.filter(
        user=user, is_deleted=False, fuel_date__gte=month_start
    ).values_list("volume_liters", flat=True):
        fuel_liters += liters or Decimal(0)

    expenses_month = (
        accumulate(FuelEntry, "fuel_date", "total_cost")
        + accumulate(Purchase, "purchase_date", "amount")
        + accumulate(Service, "service_date", "amount")
        + accumulate(Fine, "fine_date", "amount")
    )
    fuel_month = accumulate(FuelEntry, "fuel_date", "total_cost")

    avg_consumption = (
        fuel_summary(default.pk)["avg_consumption"] if default else None
    )

    recent_events = _dashboard_recent_events(user)

    insurances = Insurance.objects.filter(
        user=user,
        is_deleted=False,
        end_date__isnull=False,
        end_date__gte=now,
        end_date__lte=deadline,
        renewed_by__isnull=True,
    )
    expiring_insurances = [
        {
            "vehicle": i.vehicle,
            "insurance_type": i.get_insurance_type_display(),
            "days_left": (i.end_date - now).days,
            "end_date": i.end_date,
        }
        for i in insurances.select_related("vehicle")
    ]

    unpaid_fines = list(
        Fine.objects.filter(
            user=user, is_deleted=False, status="unpaid"
        )
    )
    unpaid_fines_sum = sum((f.amount or Decimal(0)) for f in unpaid_fines)

    planned = (
        PlannedEvent.objects.filter(
            user=user,
            is_deleted=False,
            is_done=False,
            planned_date__gte=timezone.now(),
        )
        .select_related("vehicle")
        .order_by("planned_date")
    )
    upcoming_planned = [
        {
            "description": e.description or str(e.pk),
            "vehicle": e.vehicle,
            "planned_date": e.planned_date,
            "estimated_cost": e.estimated_cost,
        }
        for e in planned[:5]
    ]

    return {
        "vehicles": vehicles,
        "vehicle_count": len(vehicles),
        "total_mileage": sum((v.current_mileage or 0) for v in vehicles),
        "default_vehicle": default,
        "expenses_month": expenses_month,
        "fuel_month": fuel_month,
        "fuel_liters": fuel_liters,
        "avg_consumption": avg_consumption,
        "recent_events": recent_events,
        "expiring_insurances": expiring_insurances,
        "unpaid_fines_count": len(unpaid_fines),
        "unpaid_fines_sum": unpaid_fines_sum,
        "upcoming_planned": upcoming_planned,
    }


def _dashboard_recent_events(user, limit: int = 3) -> list[dict]:
    """Последние события Бортжурнала (заправки/сервис/покупки/штрафы)."""
    events: list[dict] = []

    for e in FuelEntry.objects.filter(
        user=user, is_deleted=False
    ).select_related("vehicle", "station").order_by("-fuel_date")[:limit]:
        events.append({
            "kind": "fuel",
            "title": e.station.name if e.station else "fuel",
            "detail": f"{e.volume_liters or 0} л · {e.total_cost or 0} ₽",
            "vehicle": e.vehicle,
            "date": e.fuel_date or timezone.now().date(),
        })
    for e in Service.objects.filter(
        user=user, is_deleted=False
    ).select_related("vehicle").order_by("-service_date")[:limit]:
        events.append({
            "kind": "service",
            "title": e.work_description or str(e.pk),
            "detail": f"{e.amount or 0} ₽",
            "vehicle": e.vehicle,
            "date": e.service_date or timezone.now().date(),
        })
    for e in Purchase.objects.filter(
        user=user, is_deleted=False
    ).select_related("vehicle").order_by("-purchase_date")[:limit]:
        events.append({
            "kind": "purchase",
            "title": e.title,
            "detail": f"{e.amount or 0} ₽",
            "vehicle": e.vehicle,
            "date": e.purchase_date or timezone.now().date(),
        })
    for e in Fine.objects.filter(
        user=user, is_deleted=False
    ).select_related("vehicle").order_by("-fine_date")[:limit]:
        events.append({
            "kind": "fine",
            "title": e.description or e.decision_number or str(e.pk),
            "detail": f"{e.amount or 0} ₽",
            "vehicle": e.vehicle,
            "date": e.fine_date or timezone.now().date(),
        })

    events.sort(key=lambda x: x["date"], reverse=True)
    return events[:limit]


def stats_overview(vehicle_id) -> dict:
    """Агрегаты вкладки «Статистика»: KPI, графики, топ-5 и разбивка.

    Возвращает данные для карточек-показателей, столбчатого графика расходов,
    графика расхода топлива, списка топ-5 статей и круговой (кольцевой)
    диаграммы расходов по категориям.
    """
    monthly = monthly_cost(vehicle_id)
    categories = expenses_by_category(vehicle_id)
    fuel = fuel_summary(vehicle_id)

    total = sum((c["total"] for c in categories), Decimal(0))
    max_total = max((m["total"] for m in monthly), default=Decimal(0))
    max_cat = categories[0]["total"] if categories else Decimal(1)

    circum = Decimal("302")
    consumed = Decimal(0)
    for c in categories:
        pct = (c["total"] / total * 100) if total else Decimal(0)
        c["pct"] = pct
        c["dash"] = (pct / 100 * circum).quantize(Decimal("0.1"))
        c["dashoffset"] = -(consumed.quantize(Decimal("0.1")))
        consumed += pct / 100 * circum

    mileage = (
        Vehicle.objects.filter(pk=vehicle_id, is_deleted=False)
        .values_list("current_mileage", flat=True)
        .first()
        or 0
    )
    history = consumption_history(vehicle_id)
    consumption_max = max(
        (m["consumption"] for m in history), default=Decimal(0)
    ) or Decimal(1)
    return {
        "total_cost": total,
        "total_display": (total / 1000).quantize(Decimal("0.1")) if total else Decimal(0),
        "avg_consumption": fuel["avg_consumption"],
        "cost_per_km": fuel["cost_per_km"],
        "avg_price": fuel["avg_price"],
        "monthly": monthly,
        "monthly_max": max_total or Decimal(1),
        "consumption_history": history,
        "consumption_max": consumption_max,
        "categories": categories,
        "category_top": categories[:5],
        "category_max": max_cat or Decimal(1),
        "mileage": mileage,
    }


