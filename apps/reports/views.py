from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from apps.core.i18n import t
from apps.planner.models import Project

from .exporters import DATASETS, ExportContext, pdf_response, xlsx_response
from .services import (
    planner_burndown,
    planner_report_data,
    planner_top_longest,
    resolve_period,
    service_forecast,
    user_vehicles,
    vehicle_report_data,
)


def home(request):
    """Landing /reports/ — выбор раздела отчётов (ТЗ 9.3, 11.1–11.2)."""
    return render(request, "reports/home.html", {"active_page": "reports"})


def _export_context(request) -> ExportContext:
    start, end, _period = resolve_period(request)
    scope = request.GET.get("scope")
    if scope not in ("personal", "work"):
        scope = "work"
    return ExportContext(
        user=request.user,
        start=start,
        end=end,
        vehicle_id=request.GET.get("vehicle") or "",
        scope_code=scope,
        project_id=request.GET.get("project") or "",
    )


def export_xlsx(request, dataset):
    """Экспорт отчётов и списков в .xlsx (ТЗ 11.3) — тот же датасет, что на страницах."""
    builder = DATASETS.get(dataset)
    if builder is None:
        raise Http404
    payload = builder(_export_context(request))
    return xlsx_response(payload, f"mynotes-{dataset}.xlsx")


def _pdf_meta(request, ctx: ExportContext, period: str, dataset: str) -> list[str]:
    lines = []
    if period == "custom" and ctx.start:
        lines.append(f'{t("rep.filter.period")}: {ctx.start.strftime("%d.%m.%Y")} — {ctx.end.strftime("%d.%m.%Y")}')
    elif period == "all":
        lines.append(f'{t("rep.filter.period")}: {t("rep.period.all")}')
    else:
        lines.append(f'{t("rep.filter.period")}: {t(f"rep.period.{period}")}')
    if ctx.vehicle_id:
        vehicles = user_vehicles(request.user, ctx.vehicle_id)
        if vehicles:
            lines.append(f'{t("rep.filter.vehicle")}: {vehicles[0]}')
    if dataset in ("planner_report", "events", "tasks", "projects") or ctx.project_id:
        if ctx.project_id:
            project = Project.objects.filter(user=request.user, pk=ctx.project_id, is_deleted=False).first()
            if project:
                lines.append(f'{t("rep.filter.project")}: {project.title}')
        lines.append(f'{t("rep.scope.title")}: {t(f"rep.scope.{ctx.scope_code}")}')
    lines.append(f'{t("exp.meta.generated")}: {timezone.localtime().strftime("%d.%m.%Y %H:%M")}')
    return lines


def export_pdf(request, dataset):
    """PDF (WeasyPrint, ТЗ 11.3) — A4-документ с теми же данными, что и таблица на экране."""
    builder = DATASETS.get(dataset)
    if builder is None:
        raise Http404
    _, _, period = resolve_period(request)
    ctx = _export_context(request)
    payload = builder(ctx)
    return pdf_response(payload, f"mynotes-{dataset}.pdf", _pdf_meta(request, ctx, period, dataset))


def vehicle_report(request):
    """Отчёты Бортжурнала (ТЗ 11.1) — по макету 23-reports-vehicle.html."""
    start, end, period = resolve_period(request)
    selected = request.GET.get("vehicle") or ""
    all_vehicles = user_vehicles(request.user)
    vehicles = [v for v in all_vehicles if str(v.pk) == selected] if selected else all_vehicles
    report = charts = forecast = None
    if vehicles:
        report = vehicle_report_data(request.user, vehicles, start, end)
        forecast = service_forecast(request.user, vehicles)
        monthly = report["monthly"]
        categories = report["categories"]
        consumption = report["consumption"]
        charts = {
            "monthly": {
                "labels": [m["label"] for m in monthly],
                "series": [
                    {"name": t("rep.chart.fuel"), "data": [float(m["fuel"]) for m in monthly]},
                    {"name": t("rep.chart.other"), "data": [float(m["other"]) for m in monthly]},
                ],
                "colors": ["#3B82F6", "#CBD5E1"],
            },
            "categories": {
                "labels": [c["name"] for c in categories],
                "series": [float(c["total"]) for c in categories],
                "colors": [c["color"] for c in categories],
            },
            "consumption": {
                "labels": [c["label"] for c in consumption],
                "series": [{"name": t("rep.chart.consumption"), "data": [c["value"] for c in consumption]}],
            },
        }
    return render(
        request,
        "reports/vehicle.html",
        {
            "active_page": "reports",
            "start": start,
            "end": end,
            "period": period,
            "all_vehicles": all_vehicles,
            "vehicles": vehicles,
            "selected": selected,
            "report": report,
            "charts": charts,
            "forecast": forecast,
        },
    )


def planner_report(request):
    """Отчёты Записной книжки (ТЗ 11.2) — по макету 24-reports-planner.html."""
    start, end, period = resolve_period(request)
    scope_code = request.GET.get("scope")
    if scope_code not in ("personal", "work"):
        scope_code = "work"
    project_selected = request.GET.get("project") or ""
    all_projects = list(
        Project.objects.filter(
            user=request.user, is_deleted=False, scope__code=scope_code, is_archived=False
        ).order_by("created_at")
    )
    report = planner_report_data(request.user, scope_code, start, end)
    burndown = planner_burndown(request.user, scope_code, start, end, project_selected or None)
    top = planner_top_longest(request.user, scope_code, start, end)
    charts = {
        "statuses": {
            "labels": [row["name"] for row in report["by_status"]],
            "series": [{"name": t("rep.chart.tasks"), "data": [row["count"] for row in report["by_status"]]}],
            "colors": [row["color"] for row in report["by_status"]],
        },
        "burndown": None,
        "weekly": {
            "labels": [row["label"] for row in report["weekly"]],
            "series": [
                {"name": t("rep.chart.created"), "data": [row["created"] for row in report["weekly"]]},
                {"name": t("rep.chart.closed"), "data": [row["closed"] for row in report["weekly"]]},
            ],
            "colors": ["#94A3B8", "#10B981"],
        },
        "on_time": {
            "labels": [t("rep.row.on_time"), t("rep.row.late"), t("rep.row.overdue_open")],
            "series": [report["on_time"]["done_on_time"], report["on_time"]["done_late"], report["on_time"]["overdue_open"]],
            "colors": ["#10B981", "#EF4444", "#F59E0B"],
        },
    }
    if burndown:
        charts["burndown"] = {
            "labels": [p["label"] for p in burndown["points"]],
            "series": [
                {"name": t("rep.chart.burndown_actual"), "data": [p["remaining"] for p in burndown["points"]]},
                {"name": t("rep.chart.burndown_ideal"), "data": [p["ideal"] for p in burndown["points"]]},
            ],
            "colors": [burndown["project_color"], "#94A3B8"],
        }
    return render(
        request,
        "reports/planner.html",
        {
            "active_page": "reports",
            "start": start,
            "end": end,
            "period": period,
            "periods": [
                ("3m", t("rep.period.3m")),
                ("6m", t("rep.period.6m")),
                ("12m", t("rep.period.12m")),
                ("all", t("rep.period.all")),
                ("custom", t("rep.period.custom")),
            ],
            "scope_code": scope_code,
            "all_projects": all_projects,
            "project_selected": project_selected,
            "report": report,
            "burndown": burndown,
            "top": top,
            "charts": charts,
        },
    )
