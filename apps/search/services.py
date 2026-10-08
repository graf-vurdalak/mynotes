"""Сервис глобального поиска по всем сущностям (ТЗ 4.4, этап 7.7).

Сочетает два механизма PostgreSQL, каждый — отдельным индексным запросом
(фикс ревью №11: единый OR из неиндексируемых веток обесценивал GIN-индексы):

* pg_trgm — ``icontains`` по ЛОКАЛЬНЫМ текстовым полям (BitmapOr по
  gin_trgm_ops из миграций apps/search), по join-полям — предварительным
  resolve id маленьких справочников (их name тоже под trgm в 0002);
* tsvector — ``SearchVector(config='russian')`` + ``SearchQuery``/``SearchRank``
  для морфологии, отдельным запросом; ранг берётся отсюда, ILIKE/tag-ветки
  получают эвристику (_ARM_*), итог — max.

``tags @>`` — GIN из 0002. Все выборки фильтруются по ``user`` и
``is_deleted=False`` (IDOR, ТЗ 8.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import format_html, format_html_join

from apps.core.i18n import t

CONFIG = "russian"

# Эвристики ранга для не-tsvector веток (ts_rank даёт 0..1 сам)
_ARM_ILIKE = 0.6
_ARM_TAG = 0.7
_ARM_JOIN = 0.4


@dataclass(frozen=True)
class EntitySpec:
    key: str
    model: str  # "app_label.Model"
    fts_fields: tuple  # локальные поля для to_tsvector
    ilike_fields: tuple  # локальные + join поля для ILIKE (gin_trgm)
    title_fn: object
    subtitle_fn: object
    url_fn: object
    related: tuple = ()
    has_project: bool = False
    icon: str = ""
    extra_q: object = None  # callable() -> Q: доп. фиксированный фильтр


def _money(value, currency="RUB"):
    if value is None:
        return ""
    v = Decimal(value)
    s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{s} {currency}"


def _d(value):
    return date_filter(value) if value else ""


def _dt(value):
    return date_format(value, "DATETIME_FORMAT") if value else ""


def _vehicle_name(obj):
    return str(obj.vehicle) if obj.vehicle_id else ""


def _join(*parts):
    return format_html_join(" · ", "{}", ((part,) for part in parts if part))


# --- titles -----------------------------------------------------------------

def _vehicle_title(o):
    return str(o)


def _vehicle_subtitle(o):
    bits = [_d(o.purchase_date) or t("search.without_date"), o.license_plate]
    if o.year:
        bits.append(str(o.year))
    return _join(*bits)


def _fuel_title(o):
    return o.station.name if o.station_id else (o.station_custom_name or t("search.no_station"))


def _fuel_subtitle(o):
    return _join(_d(o.fuel_date), _vehicle_name(o), _money(o.total_cost, o.currency_code))


def _purchase_title(o):
    return o.title


def _purchase_subtitle(o):
    return _join(
        _d(o.purchase_date), o.category.name if o.category_id else "",
        _money(o.amount, o.currency_code),
    )


def _service_title(o):
    return o.work_description or o.service_station or t("search.no_description")


def _service_subtitle(o):
    return _join(
        _d(o.service_date), _vehicle_name(o), o.service_station,
        _money(o.amount, o.currency_code),
    )


def _fine_title(o):
    return o.decision_number or (o.article or t("search.fine") + f" {_d(o.fine_date)}")


def _fine_subtitle(o):
    return _join(
        _d(o.fine_date), o.article, _vehicle_name(o),
        _money(o.amount, o.currency_code), o.get_status_display(),
    )


def _insurance_title(o):
    return o.company or o.get_insurance_type_display()


def _insurance_subtitle(o):
    return _join(
        o.get_insurance_type_display(),
        o.policy_number,
        _d(o.start_date), _d(o.end_date),
        _vehicle_name(o), _money(o.cost, o.currency_code),
    )


def _planned_title(o):
    return o.description or t("search.planned")


def _planned_subtitle(o):
    return _join(
        _dt(o.planned_date), o.location, _vehicle_name(o),
        _money(o.estimated_cost, o.currency_code),
    )


def _event_title(o):
    return o.title


def _event_subtitle(o):
    tags = " ".join(f"#{tag}" for tag in (o.tags or [])[:3])
    return _join(
        _dt(o.start_at),
        t("pl.scope_work") if o.scope_id and o.scope.code == "work" else "",
        o.project.title if o.project_id else "",
        o.status.name if o.status_id else "",
        tags,
    )


def _event_url(o):
    if o.scope_id and o.scope.code == "work":
        return reverse("planner:task", args=[o.pk])
    return reverse("planner:event_update", args=[o.pk])


def _project_title(o):
    return o.title


def _project_subtitle(o):
    return _join(_d(o.created_at), o.description[:80])


def _detail_tab(tab):
    def fn(o):
        return reverse("vehicles:detail", args=[o.vehicle_id]) + f"?tab={tab}"
    return fn


# Ревью №15: task/event — одна таблица, поля задаются одним источником
_EVENT_FTS = ("title", "description", "location")
_EVENT_ILIKE = _EVENT_FTS


ENTITIES: dict[str, EntitySpec] = {
    spec.key: spec
    for spec in (
        EntitySpec("vehicle", "vehicles.Vehicle",
                   ("brand_custom", "model_custom", "notes"),
                   ("brand_custom", "model_custom", "notes", "license_plate",
                    "brand__name", "model__name"),
                   _vehicle_title, _vehicle_subtitle,
                   lambda o: reverse("vehicles:detail", args=[o.pk]),
                   related=("brand", "model"), icon="🚗"),
        EntitySpec("fuel", "vehicles.FuelEntry",
                   ("station_custom_name", "notes"),
                   ("station_custom_name", "notes", "station__name"),
                   _fuel_title, _fuel_subtitle, _detail_tab("fuel"),
                   related=("station", "vehicle"), icon="⛽"),
        EntitySpec("purchase", "vehicles.Purchase",
                   ("title", "description"),
                   ("title", "description", "category__name"),
                   _purchase_title, _purchase_subtitle, _detail_tab("purchase"),
                   related=("category", "vehicle"), icon="🛒"),
        EntitySpec("service", "vehicles.Service",
                   ("service_station", "work_description"),
                   ("service_station", "work_description"),
                   _service_title, _service_subtitle, _detail_tab("service"),
                   related=("vehicle",), icon="🔧"),
        EntitySpec("fine", "vehicles.Fine",
                   ("decision_number", "article", "description"),
                   ("decision_number", "article", "description"),
                   _fine_title, _fine_subtitle, _detail_tab("fines"),
                   related=("vehicle",), icon="🚨"),
        EntitySpec("insurance", "vehicles.Insurance",
                   ("company", "policy_number"),
                   ("company", "policy_number"),
                   _insurance_title, _insurance_subtitle, _detail_tab("insurance"),
                   related=("vehicle",), icon="🛡"),
        EntitySpec("planned", "vehicles.PlannedEvent",
                   ("description", "location"),
                   ("description", "location"),
                   _planned_title, _planned_subtitle, _detail_tab("planned"),
                   related=("vehicle",), icon="🗓"),
        EntitySpec("task", "planner.Event",
                   _EVENT_FTS, _EVENT_ILIKE,
                   _event_title, _event_subtitle, _event_url,
                   related=("scope", "project", "status"), has_project=True,
                   icon="✅", extra_q=lambda: Q(scope__code="work")),
        EntitySpec("event", "planner.Event",
                   _EVENT_FTS, _EVENT_ILIKE,
                   _event_title, _event_subtitle, _event_url,
                   related=("scope", "project", "status"), has_project=True,
                   icon="📅", extra_q=lambda: ~Q(scope__code="work")),
        EntitySpec("project", "planner.Project",
                   ("title", "description"),
                   ("title", "description"),
                   _project_title, _project_subtitle,
                   lambda o: reverse("planner:project_update", args=[o.pk]),
                   icon="📁", has_project=True),
    )
}

PER_TYPE_LIMIT = 30

_JOIN_TARGET_CACHE: dict[tuple[str, str], tuple[type, str, str]] = {}


def _join_target(model, path):
    """("station__name") → (related_model, поле, имя FK-атрибута)."""
    key = (model._meta.label, path)
    hit = _JOIN_TARGET_CACHE.get(key)
    if hit is None:
        parts = path.split("__")
        rel = model
        for p in parts[:-1]:
            rel = rel._meta.get_field(p).related_model
        hit = (rel, parts[-1], parts[0])
        _JOIN_TARGET_CACHE[key] = hit
    return hit


def _search_spec(spec, user, term, query, date_from, date_to, project_pk):
    model = django_apps.get_model(*spec.model.split("."))
    base = model.objects.filter(user=user, is_deleted=False)
    if spec.extra_q is not None:
        base = base.filter(spec.extra_q())
    if spec.has_project and project_pk:
        if spec.key == "project":
            base = base.filter(pk=project_pk)
        else:
            base = base.filter(project_id=project_pk)
    if date_from:
        base = base.filter(created_at__date__gte=date_from)
    if date_to:
        base = base.filter(created_at__date__lte=date_to)

    # Ревью №11: arms отдельно, каждый индексный (GIN trgm / GIN array /
    # маленький IN по справочнику); tsvector — своим сканом с рангом. Слияние
    # по id в python, финальная выборка объектов — одним pk__in.
    scores: dict[object, float] = {}

    q_local = Q()
    for f in spec.ilike_fields:
        if "__" not in f:
            q_local |= Q(**{f"{f}__icontains": term})
    if q_local:
        for pk in base.filter(q_local).values_list("pk", flat=True):
            scores[pk] = _ARM_ILIKE

    if spec.model == "planner.Event":
        for pk in base.filter(tags__contains=[term]).values_list("pk", flat=True):
            scores[pk] = max(scores.get(pk, 0.0), _ARM_TAG)

    for path in spec.ilike_fields:
        if "__" not in path:
            continue
        rel, field, fk_name = _join_target(model, path)
        target_ids = list(
            rel.objects.filter(**{f"{field}__icontains": term}).values_list("pk", flat=True)
        )
        if not target_ids:
            continue
        for pk in base.filter(**{f"{fk_name}__in": target_ids}).values_list("pk", flat=True):
            scores[pk] = max(scores.get(pk, 0.0), _ARM_JOIN)

    ranked = (
        base.annotate(_fts=SearchVector(*spec.fts_fields, config=CONFIG))
        .filter(_fts=query)
        .annotate(_rank=SearchRank(SearchVector(*spec.fts_fields, config=CONFIG), query))
        .values("pk", "_rank")
    )
    for row in ranked:
        scores[row["pk"]] = max(scores.get(row["pk"], 0.0), float(row["_rank"] or 0.0))

    if not scores:
        return []

    objs = (
        model.objects.filter(pk__in=list(scores))
        .select_related(*spec.related)
    )
    objs = sorted(objs, key=lambda o: (-scores[o.pk], -o.created_at.timestamp()))[:PER_TYPE_LIMIT]
    return [
        {
            "key": spec.key,
            "title": spec.title_fn(obj),
            "subtitle": spec.subtitle_fn(obj),
            "url": spec.url_fn(obj),
            "rank": scores[obj.pk],
        }
        for obj in objs
    ]


def search(term: str, user, type_keys=(), date_from=None, date_to=None, project_pk=None):
    """Группированные результаты: [(spec, hits)] в порядке лучшего ранга."""
    term = (term or "").strip()
    if not term:
        return []
    query = SearchQuery(term, config=CONFIG)
    groups = []
    for spec in ENTITIES.values():
        if type_keys and spec.key not in type_keys:
            continue
        hits = _search_spec(spec, user, term, query, date_from, date_to, project_pk)
        if hits:
            groups.append((spec, hits))
    groups.sort(key=lambda g: max(h["rank"] for h in g[1]), reverse=True)
    return groups


def highlight(text: str, term: str) -> str:
    """<mark> на каждое вхождение запроса (регистронезависимо).

    Форматтер Django экранирует данные из БД и оставляет разметку <mark> безопасной.
    """
    if not text or not term:
        return text
    pattern = re.compile("(" + re.escape(str(term)) + ")", re.I)
    parts = pattern.split(str(text))
    return format_html_join(
        "",
        "{}",
        (
            (format_html("<mark>{}</mark>", part) if index % 2 else part,)
            for index, part in enumerate(parts)
        ),
    )
