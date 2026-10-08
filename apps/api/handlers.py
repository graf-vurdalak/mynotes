"""Обработчики ``POST /api/v1/bot/ingest`` (ТЗ 6.2).

Единый gateway для обоих ботов: роутинг по ``(module, action)`` к бизнес-сервис-слою
``apps/vehicles`` и ``apps/planner``. Все чтения/записи идут только через IDOR-безопасные
выборки (``owned_queryset``/``get_owned``) с ``source='telegram'``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import make_aware
from rest_framework.exceptions import ValidationError

from apps.planner import services as planner_services
from apps.planner.models import Event, Project, Scope, Status
from apps.references.models import FuelStation
from apps.vehicles import services as vehicle_services
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    Insurance,
    Purchase,
    PurchaseCategory,
    Service,
    Vehicle,
)

from .models import BotUpload

# ---------------------------------------------------------------------------
# Разбор payload
# ---------------------------------------------------------------------------


def _req(payload: dict, key: str):
    if payload.get(key) in (None, ""):
        raise ValidationError(f"Поле '{key}' обязательно")
    return payload[key]


def _opt(payload: dict, key: str, default=None):
    value = payload.get(key)
    return default if value in (None, "") else value


def _int(payload, key, required=False, default=None):
    raw = _req(payload, key) if required else _opt(payload, key, default)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ValidationError(f"'{key}' — целое число ожидалось")


def _dec(payload, key, required=False, default=None):
    raw = _req(payload, key) if required else _opt(payload, key, default)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"'{key}' — число ожидалось")


def _bool(payload, key, default=False):
    raw = payload.get(key, default)
    if isinstance(raw, str):
        return raw.lower() in ("1", "true", "yes", "да")
    return bool(raw)


def _date_val(payload, key, default=None):
    raw = _opt(payload, key, default)
    if raw is None or isinstance(raw, date):
        return raw or timezone.localdate()
    parsed = parse_date(str(raw))
    if parsed is None:
        raise ValidationError(f"'{key}' — дата в формате YYYY-MM-DD")
    return parsed


def _dt_val(payload, key):
    raw = _opt(payload, key)
    if raw is None:
        return None
    parsed = parse_datetime(str(raw))
    if parsed is None:
        raise ValidationError(f"'{key}' — дата-время (ISO 8601)")
    if timezone.is_naive(parsed):
        parsed = make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _str(payload, key, required=False, default=""):
    raw = _req(payload, key) if required else _opt(payload, key, default)
    return "" if raw is None else str(raw)


def _currency(user) -> str:
    """Валюта по умолчанию из профил-настроек; устойчиво к отсутствию UserSettings."""
    try:
        return user.settings.default_currency
    except Exception:
        return "RUB"


def _get_vehicle(user, payload):
    pk = _req(payload, "vehicle_id")
    try:
        return vehicle_services.get_owned(Vehicle, user, pk)
    except Vehicle.DoesNotExist:
        raise ValidationError("Автомобиль не найден или не принадлежит пользователю")


def _attach_staged(obj, field: str, upload_id):
    """Переносит staged-файл (BotUpload) в ImageField сущности и удаляет staging."""
    if not upload_id:
        return
    upload = BotUpload.objects.filter(pk=upload_id, user=obj.user).first()
    if upload is None:
        raise ValidationError(f"upload_id '{upload_id}' не найден")
    upload.file.open("rb")
    content = upload.file.read()
    upload.file.close()
    from django.core.files.base import ContentFile

    setattr(obj, field, ContentFile(content, name=f"{obj.id}{upload.extension}"))
    upload.delete()


# ---------------------------------------------------------------------------
# Vehicle — чтения
# ---------------------------------------------------------------------------


def vehicle_vehicles(user, payload):
    qs = vehicle_services.owned_queryset(Vehicle, user).select_related("brand", "model")
    data = [
        {
            "id": str(v.id),
            "name": str(v),
            "plate": v.license_plate,
            "is_default": v.is_default,
            "mileage": v.current_mileage or 0,
        }
        for v in qs
    ]
    return {"data": data}


def vehicle_set_default(user, payload):
    vehicle = _get_vehicle(user, payload)
    vehicle_services.set_default_vehicle(user, vehicle)
    return {"entity_id": str(vehicle.id)}


def vehicle_insurances(user, payload):
    vehicle = _get_vehicle(user, payload)
    qs = Insurance.objects.filter(vehicle=vehicle, is_deleted=False).order_by("-end_date")
    data = [
        {
            "id": str(i.id),
            "type": i.get_insurance_type_display(),
            "company": i.company,
            "number": i.policy_number,
            "end_date": i.end_date.isoformat() if i.end_date else None,
            "cost": str(i.cost),
        }
        for i in qs[:20]
    ]
    return {"data": data}


def vehicle_stats(user, payload):
    overview = vehicle_services.dashboard_overview(user)
    default = overview["default_vehicle"]
    fuel = vehicle_services.fuel_summary(default.pk) if default else {}
    return {
        "data": {
            "vehicle": str(default) if default else None,
            "mileage": default.current_mileage if default else 0,
            "expenses_month": str(overview["expenses_month"]),
            "fuel_month": str(overview["fuel_month"]),
            "fuel_liters": str(overview["fuel_liters"]),
            "avg_consumption": str(fuel.get("avg_consumption") or ""),
            "unpaid_fines_count": overview["unpaid_fines_count"],
            "unpaid_fines_sum": str(overview["unpaid_fines_sum"]),
        }
    }


def vehicle_search_records(user, payload):
    """Inline-поиск по заправкам/покупкам (ТЗ 7.5): станция/название/категория."""
    term = _str(payload, "query").strip()
    limit = _int(payload, "limit", default=10) or 10
    results: list[dict] = []

    fuel_qs = FuelEntry.objects.filter(user=user, is_deleted=False)
    purchase_qs = Purchase.objects.filter(user=user, is_deleted=False)
    if term:
        fuel_qs = fuel_qs.filter(
            Q(station__name__icontains=term) | Q(station_custom_name__icontains=term)
            | Q(fuel_type__icontains=term)
        )
        purchase_qs = purchase_qs.filter(
            Q(title__icontains=term) | Q(category__name__icontains=term)
        )

    for e in fuel_qs.select_related("station").order_by("-fuel_date")[:limit]:
        results.append({
            "kind": "fuel",
            "id": str(e.id),
            "title": (e.station.name if e.station else e.station_custom_name) or "Заправка",
            "date": e.fuel_date.isoformat(),
            "detail": f"{e.volume_liters or 0} л · {e.total_cost or 0} {e.currency_code}",
        })
    for p in purchase_qs.select_related("category").order_by("-purchase_date")[:limit]:
        results.append({
            "kind": "purchase",
            "id": str(p.id),
            "title": p.title,
            "date": p.purchase_date.isoformat() if p.purchase_date else None,
            "detail": f"{p.amount} {p.currency_code}",
        })
    results.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"data": results[:limit]}


# ---------------------------------------------------------------------------
# Vehicle — записи
# ---------------------------------------------------------------------------


def _resolve_station(user, payload):
    station_id = _opt(payload, "station_id")
    if station_id:
        station = FuelStation.objects.filter(
            pk=station_id, is_system=True
        ).first() or FuelStation.objects.filter(
            pk=station_id, created_by=user
        ).first()
        if station is None:
            raise ValidationError("АЗС не найдена")
        return station, ""
    name = _str(payload, "station_name")
    if name:
        station = FuelStation.objects.filter(name__iexact=name).first()
        return station, "" if station else name
    return None, _str(payload, "station_custom_name")


def vehicle_create_fuel(user, payload):
    vehicle = _get_vehicle(user, payload)
    station, custom = _resolve_station(user, payload)
    entry = FuelEntry(
        user=user,
        vehicle=vehicle,
        station=station,
        station_custom_name=custom,
        fuel_date=_date_val(payload, "fuel_date"),
        odometer=_int(payload, "odometer", required=True),
        fuel_type=_str(payload, "fuel_type"),
        volume_liters=_dec(payload, "volume_liters", required=True),
        price_per_liter=_dec(payload, "price_per_liter"),
        total_cost=_dec(payload, "total_cost", default=0),
        currency_code=_str(payload, "currency_code", default=_currency(user)),
        full_tank=_bool(payload, "full_tank"),
        latitude=_dec(payload, "latitude"),
        longitude=_dec(payload, "longitude"),
        notes=_str(payload, "notes"),
        source="telegram",
    )
    vehicle_services.recalc_fuel_entry_totals(entry, commit=False)
    vehicle_services.resolve_fuel_station(entry, user)
    entry.save()
    vehicle_services.recalc_vehicle_mileage(vehicle)
    return {"entity_id": str(entry.id)}


def vehicle_create_purchase(user, payload):
    vehicle = _get_vehicle(user, payload)
    purchase = Purchase(
        user=user,
        vehicle=vehicle,
        category_id=_opt(payload, "category_id"),
        title=_str(payload, "title", required=True),
        description=_str(payload, "description"),
        amount=_dec(payload, "amount", required=True),
        currency_code=_str(payload, "currency_code", default=_currency(user)),
        purchase_date=_date_val(payload, "purchase_date"),
        odometer=_int(payload, "odometer"),
        items=_opt(payload, "items", []),
        source="telegram",
    )
    purchase.save()
    _attach_staged(purchase, "photo", _opt(payload, "upload_id"))
    if purchase.photo:
        purchase.save()
    if purchase.odometer:
        vehicle_services.recalc_vehicle_mileage(vehicle)
    return {"entity_id": str(purchase.id)}


def vehicle_create_service(user, payload):
    vehicle = _get_vehicle(user, payload)
    service = Service(
        user=user,
        vehicle=vehicle,
        service_station=_str(payload, "service_station"),
        work_description=_str(payload, "work_description", required=True),
        amount=_dec(payload, "amount", required=True),
        currency_code=_str(payload, "currency_code", default=_currency(user)),
        service_date=_date_val(payload, "service_date"),
        odometer=_int(payload, "odometer"),
        order_document=_str(payload, "order_document"),
        source="telegram",
    )
    service.save()
    for idx, upload_id in enumerate(_opt(payload, "upload_ids", []) or []):
        upload = BotUpload.objects.filter(pk=upload_id, user=user).first()
        if upload is None:
            raise ValidationError(f"upload_id '{upload_id}' не найден")
        upload.file.open("rb")
        content = upload.file.read()
        upload.file.close()
        from django.core.files.base import ContentFile

        photo = service.photos.create(
            image=ContentFile(content, name=f"{service.id}_{idx}{upload.extension}"),
            sort_order=idx,
        )
        upload.delete()
        del photo
    if service.odometer:
        vehicle_services.recalc_vehicle_mileage(vehicle)
    return {"entity_id": str(service.id)}


def vehicle_create_fine(user, payload):
    vehicle = _get_vehicle(user, payload)
    fine = Fine(
        user=user,
        vehicle=vehicle,
        fine_date=_date_val(payload, "fine_date"),
        decision_number=_str(payload, "decision_number"),
        article=_str(payload, "article"),
        description=_str(payload, "description"),
        amount=_dec(payload, "amount", required=True),
        currency_code=_str(payload, "currency_code", default=_currency(user)),
        status=_str(payload, "status", default="unpaid"),
        paid_at=_date_val(payload, "paid_at") if _opt(payload, "paid_at") else None,
        link_purchase=_bool(payload, "link_purchase"),
        source="telegram",
    )
    if fine.status not in dict(Fine.STATUSES):
        raise ValidationError("Недопустимый статус штрафа")
    fine.save()
    _attach_staged(fine, "photo", _opt(payload, "upload_id"))
    if fine.photo:
        fine.save()
    if fine.link_purchase:
        vehicle_services.sync_fine_purchase(fine, user, link=True)
    return {"entity_id": str(fine.id)}


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def _scope(user, code):
    try:
        return planner_services.get_scope(user, code)
    except KeyError:
        raise ValidationError(f"Скоуп '{code}' недоступен")


def _project(user, payload, scope):
    pid = _opt(payload, "project_id")
    if not pid:
        return None
    project = planner_services.get_owned(Project, user, pid)
    if project is None:
        raise ValidationError("Проект не найден")
    if project.scope_id != scope.id:
        raise ValidationError("Проект из другого скоупа")
    return project


def _status_by_code(user, code):
    if not code:
        return None
    status = Status.objects.filter(user=user, code=code, is_deleted=False).first()
    if status is None:
        raise ValidationError(f"Статус '{code}' не найден")
    return status


def planner_list_projects(user, payload):
    qs = planner_services.owned_queryset(Project, user).select_related("scope")
    return {
        "data": [
            {
                "id": str(p.id),
                "title": p.title,
                "color": p.color,
                "scope": p.scope.code,
                "is_archived": p.is_archived,
            }
            for p in qs
        ]
    }


def planner_list_events(user, payload):
    scope_code = _str(payload, "scope", default="personal") or "personal"
    items = planner_services.upcoming_events(user, scope_code, limit=10)
    data = [
        {
            "id": str(x["event"].id),
            "title": x["event"].title,
            "start": x["start"].isoformat(),
            "recurring": x["recurring"],
            "project": x["event"].project.title if x["event"].project else None,
        }
        for x in items
    ]
    return {"data": data}


def planner_list_tasks(user, payload):
    qs = planner_services.owned_queryset(
        Event, user, scope__code=Scope.WORK, event_type="task"
    ).select_related("status")
    data = [
        {
            "id": str(e.id),
            "title": e.title,
            "status": e.status.code if e.status else None,
            "priority": e.priority,
            "due_at": e.due_at.isoformat() if e.due_at else None,
        }
        for e in qs.order_by("status__sort_order", "-created_at")[:30]
    ]
    return {"data": data}


def planner_search(user, payload):
    query = _str(payload, "query", required=True)
    scope_code = _opt(payload, "scope")
    events = planner_services.search_events(user, scope_code, query, limit=15)
    data = [
        {
            "id": str(e.id),
            "title": e.title,
            "scope": e.scope.code,
            "status": e.status.name if e.status else None,
            "start": e.start_at.isoformat() if e.start_at else None,
        }
        for e in events
    ]
    return {"data": data}


def planner_create_task(user, payload):
    scope = _scope(user, "work")
    status = _status_by_code(user, _opt(payload, "status"))
    if status is None:
        planner_services.ensure_statuses(user, scope)
        status = planner_services.default_status_for(user)
    event = Event(
        user=user,
        scope=scope,
        project=_project(user, payload, scope),
        status=status,
        title=_str(payload, "title", required=True),
        description=_str(payload, "description"),
        event_type="task",
        priority=_str(payload, "priority", default="normal"),
        due_at=_dt_val(payload, "due_at"),
        tags=_opt(payload, "tags", []) or [],
        estimated_minutes=_int(payload, "estimated_minutes"),
        source="telegram",
    )
    if event.priority not in dict(Event.PRIORITIES):
        raise ValidationError("Недопустимый приоритет")
    event.save()
    return {"entity_id": str(event.id)}


def planner_create_event(user, payload):
    scope = _scope(user, "personal")
    event = Event(
        user=user,
        scope=scope,
        project=_project(user, payload, scope),
        title=_str(payload, "title", required=True),
        description=_str(payload, "description"),
        event_type=_str(payload, "event_type", default="meeting"),
        priority=_str(payload, "priority", default="normal"),
        start_at=_dt_val(payload, "start_at"),
        end_at=_dt_val(payload, "end_at"),
        location=_str(payload, "location"),
        tags=_opt(payload, "tags", []) or [],
        reminder_minutes_before=_int(payload, "reminder_minutes_before"),
        source="telegram",
    )
    if event.priority not in dict(Event.PRIORITIES):
        raise ValidationError("Недопустимый приоритет")
    event.save()
    return {"entity_id": str(event.id)}


# ---------------------------------------------------------------------------
# Реестр (module, action) → handler
# ---------------------------------------------------------------------------

ACTIONS = {
    ("vehicle", "list_vehicles"): vehicle_vehicles,
    ("vehicle", "set_default_vehicle"): vehicle_set_default,
    ("vehicle", "list_insurances"): vehicle_insurances,
    ("vehicle", "stats"): vehicle_stats,
    ("vehicle", "search_records"): vehicle_search_records,
    ("vehicle", "create_fuel"): vehicle_create_fuel,
    ("vehicle", "create_purchase"): vehicle_create_purchase,
    ("vehicle", "create_service"): vehicle_create_service,
    ("vehicle", "create_fine"): vehicle_create_fine,
    ("planner", "list_projects"): planner_list_projects,
    ("planner", "list_events"): planner_list_events,
    ("planner", "list_tasks"): planner_list_tasks,
    ("planner", "search"): planner_search,
    ("planner", "create_task"): planner_create_task,
    ("planner", "create_event"): planner_create_event,
}


def dispatch(module: str, action: str, user, payload: dict) -> dict:
    handler = ACTIONS.get((module, action))
    if handler is None:
        raise ValidationError(f"Неизвестное действие: {module}/{action}")
    result = handler(user, payload or {})
    if "entity_id" in result:
        return {"status": "ok", "entity_id": result["entity_id"]}
    return {"status": "ok", "data": result.get("data", [])}


# ---------------------------------------------------------------------------
# Справочники GET /api/v1/bot/references/{type} (ТЗ 6.2)
# ---------------------------------------------------------------------------


def ref_vehicles(user):
    qs = vehicle_services.owned_queryset(Vehicle, user).select_related("brand", "model")
    return [
        {"id": str(v.id), "name": str(v), "plate": v.license_plate,
         "is_default": v.is_default, "mileage": v.current_mileage or 0}
        for v in qs
    ]


def ref_fuel_stations(user):
    recent = {s.id for s in vehicle_services.recent_fuel_stations(user)}
    qs = FuelStation.objects.filter(Q(is_system=True) | Q(created_by=user)).order_by("name")
    return [
        {"id": str(s.id), "name": s.name, "recent": s.id in recent}
        for s in qs
    ]


def ref_purchase_categories(user):
    qs = PurchaseCategory.objects.filter(Q(user__isnull=True) | Q(user=user)).order_by("sort_order", "name")
    return [{"id": str(c.id), "name": c.name, "color": c.color} for c in qs]


def ref_statuses(user):
    qs = Status.objects.filter(user=user, is_deleted=False).order_by("sort_order")
    return [{"code": s.code, "name": s.name, "color": s.color} for s in qs]


def ref_projects(user):
    qs = planner_services.owned_queryset(Project, user).select_related("scope")
    return [{"id": str(p.id), "title": p.title, "color": p.color, "scope": p.scope.code} for p in qs]


def ref_scopes(user):
    scopes = planner_services.guarantee_scopes(user)
    return [{"code": s.code, "name": s.name} for s in scopes.values()]


REFERENCES = {
    "vehicles": ref_vehicles,
    "fuel_stations": ref_fuel_stations,
    "purchase_categories": ref_purchase_categories,
    "statuses": ref_statuses,
    "projects": ref_projects,
    "scopes": ref_scopes,
}
