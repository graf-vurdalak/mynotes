"""Страница глобального поиска /search/ (ТЗ 4.4, этап 7.7)."""

import uuid
from urllib.parse import urlencode

from django.shortcuts import render
from django.utils.dateparse import parse_date

from apps.core.i18n import t
from . import services
from .services import ENTITIES


def _clean_project_pk(raw: str) -> str | None:
    """Ревью №6: не-UUID из GET дошёл бы до UUID-колонки как ValidationError → 500."""
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError):
        return None


def _results_url(term, type_keys, raw_from, raw_to, project, replace_type=None):
    params = {}
    if term:
        params["q"] = term
    types = list(type_keys)
    if replace_type is not None:
        types = [replace_type] if replace_type else []
    if types:
        params["type"] = ",".join(types)
    if raw_from:
        params["date_from"] = raw_from
    if raw_to:
        params["date_to"] = raw_to
    if project:
        params["project"] = project
    return "/search/?" + urlencode(params)


def search_page(request):
    term = request.GET.get("q", "").strip()
    type_keys = tuple(k for k in request.GET.get("type", "").split(",") if k in ENTITIES)
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")
    project_raw = (request.GET.get("project") or "").strip()
    project_pk = _clean_project_pk(project_raw)

    groups = []
    total = 0
    if term:
        raw = services.search(
            term, request.user, type_keys, date_from, date_to, project_pk
        )
        for spec, hits in raw:
            for hit in hits:
                hit["title"] = services.highlight(hit["title"], term)
            groups.append({
                "key": spec.key,
                "icon": spec.icon,
                "label": t(f"search.type.{spec.key}"),
                "hits": hits,
            })
            total += len(hits)

    from apps.planner.models import Project

    context = {
        "q": term,
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "project": project_pk,
        "active_types": type_keys,
        "all_url": _results_url(term, type_keys, request.GET.get("date_from", ""),
                                request.GET.get("date_to", ""), project_pk, replace_type=""),
        "type_chips": [
            {
                "key": key,
                "icon": spec.icon,
                "label": t(f"search.type.{key}"),
                "url": _results_url(term, type_keys, request.GET.get("date_from", ""),
                                    request.GET.get("date_to", ""), project_pk,
                                    replace_type=key),
            }
            for key, spec in ENTITIES.items()
        ],
        "projects": Project.objects.filter(user=request.user, is_deleted=False)
        .order_by("title"),
        "groups": groups,
        "total": total,
        "active_page": "search",
    }
    return render(request, "search/results.html", context)
