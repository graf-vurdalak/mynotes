import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.i18n import t

from . import services
from .forms import CommentForm, EventForm, ProjectForm, StatusForm, TaskForm
from .models import Comment, Event, Project, Scope, Status


def _user_projects(user, scope_code):
    return list(
        Project.objects.filter(
            user=user, scope__code=scope_code, is_deleted=False, is_archived=False
        ).order_by("title")
    )


def _ctx(request, active_page="planner", **extra):
    ctx = {"active_page": active_page}
    ctx.update(extra)
    return ctx


def _safe_next(request, fallback: str) -> str:
    """Redirect-цель из ?next= только same-origin (защита от open redirect)."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return fallback


# ------------------------------------------------------------------
# Выбор скоупа (макет 16)
# ------------------------------------------------------------------

@login_required
def scope_picker(request):
    scopes = services.guarantee_scopes(request.user)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    personal_events = services.upcoming_events(request.user, Scope.PERSONAL, limit=5)
    month_end = (month_start + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    personal_month = services.events_for_range(request.user, Scope.PERSONAL, month_start, month_end)
    work_open = (
        services.owned_queryset(
            Event, request.user, scope__code=Scope.WORK
        )
        .exclude(status__code="done")
        .count()
    )
    work_in_progress = services.owned_queryset(
        Event, request.user, scope__code=Scope.WORK, status__code="in_progress"
    ).count()

    context = _ctx(
        request,
        scopes=scopes,
        personal_count=len(personal_month),
        personal_next=personal_events,
        work_open=work_open,
        work_in_progress=work_in_progress,
    )
    return render(request, "planner/scope_picker.html", context)


# ------------------------------------------------------------------
# Личный раздел: календарь + ленты (макеты 07, 17)
# ------------------------------------------------------------------

def _parse_date(request, name, default):
    raw = request.GET.get(name)
    if raw:
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            pass
    return default


@login_required
def personal_calendar(request):
    services.guarantee_scopes(request.user)
    today = timezone.localdate()
    view = request.GET.get("view", "month")
    if view not in {"month", "week", "day"}:
        view = "month"
    anchor = _parse_date(request, "date", today)

    if view == "month":
        first = anchor.replace(day=1)
        grid_start = first - dt.timedelta(days=(first.weekday()))
        grid_end = grid_start + dt.timedelta(days=41)
    elif view == "week":
        grid_start = anchor - dt.timedelta(days=anchor.weekday())
        grid_end = grid_start + dt.timedelta(days=6)
    else:
        grid_start = anchor - dt.timedelta(days=anchor.weekday())
        grid_end = grid_start + dt.timedelta(days=6)

    instances = services.events_for_range(request.user, Scope.PERSONAL, grid_start, grid_end)
    by_day: dict[dt.date, list] = {}
    for item in instances:
        by_day.setdefault(timezone.localtime(item["start"]).date(), []).append(item)

    weeks = []
    day = grid_start
    total_days = (grid_end - grid_start).days + 1
    for _ in range(max(1, total_days // 7)):
        week = []
        for _ in range(7):
            week.append({"date": day, "events": by_day.get(day, [])})
            day += dt.timedelta(days=1)
        weeks.append(week)

    selected = _parse_date(request, "selected", today)
    selected_events = by_day.get(selected, [])

    prev_date, next_date = _month_shift(view, anchor)
    month_label = _month_label(anchor)
    categories = (
        Project.objects.filter(
            user=request.user, scope__code=Scope.PERSONAL, is_deleted=False, is_archived=False
        )
        .annotate(events_count=Count("events", filter=Q(events__is_deleted=False)))
        .order_by("title")
    )

    context = _ctx(
        request,
        view=view,
        weeks=weeks,
        weekdays=[t(f"date.wd.{i}") for i in range(1, 8)],
        today=today,
        anchor=anchor,
        selected=selected,
        selected_events=selected_events,
        month_label=month_label,
        prev_date=prev_date,
        next_date=next_date,
        projects=_user_projects(request.user, Scope.PERSONAL),
        categories=categories,
        day_count=len(selected_events),
        upcoming=services.upcoming_events(request.user, Scope.PERSONAL, limit=5),
    )
    return render(request, "planner/personal_calendar.html", context)


def _month_shift(view, anchor):
    if view == "month":
        first = anchor.replace(day=1)
        prev = (first - dt.timedelta(days=1)).replace(day=1)
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
    elif view == "week":
        prev = anchor - dt.timedelta(days=7)
        nxt = anchor + dt.timedelta(days=7)
    else:
        prev = anchor - dt.timedelta(days=1)
        nxt = anchor + dt.timedelta(days=1)
    return prev, nxt


MONTH_NAMES_RU = [t(f"date.month_gen.{i}") for i in range(1, 13)]
MONTH_NAMES_NOM_RU = [t(f"date.month_nom.{i}") for i in range(1, 13)]


def _month_label(d):
    return f"{MONTH_NAMES_NOM_RU[d.month - 1]} {d.year}"


@login_required
def personal_feed(request):
    services.guarantee_scopes(request.user)
    today = timezone.localdate()
    upcoming = services.events_for_range(
        request.user, Scope.PERSONAL, today, today + dt.timedelta(days=90)
    )
    past = list(
        services.owned_queryset(
            Event, request.user, scope__code=Scope.PERSONAL, start_at__lt=timezone.now()
        )
        .filter(recurrence_rule="")
        .order_by("-start_at")[:20]
    )
    context = _ctx(
        request,
        upcoming=upcoming,
        past=past,
        projects=_user_projects(request.user, Scope.PERSONAL),
    )
    return render(request, "planner/personal_feed.html", context)


@login_required
def event_create(request):
    form = EventForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_event_saved"))
        return redirect(_safe_next(request, "/planner/personal/"))
    context = _ctx(request, form=form, is_new=True)
    return render(request, "planner/event_form.html", context)


@login_required
def event_update(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.PERSONAL)
    form = EventForm(request.user, request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_event_saved"))
        return redirect(_safe_next(request, "/planner/personal/"))
    context = _ctx(request, form=form, event=event, is_new=False)
    return render(request, "planner/event_form.html", context)


@login_required
@require_POST
def event_delete(request, pk):
    event = get_object_or_404(
        Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.PERSONAL
    )
    event.delete()
    messages.success(request, t("pl.msg_event_deleted"))
    return redirect(_safe_next(request, "/planner/personal/"))


# ------------------------------------------------------------------
# Рабочий раздел: Kanban (макеты 06, 18, 19)
# ------------------------------------------------------------------

def _kanban_filters(request):
    return {
        "project": request.GET.get("project", ""),
        "priority": request.GET.get("priority", ""),
        "tag": request.GET.get("tag", ""),
        "q": request.GET.get("q", ""),
    }


def _work_queryset(request, filters):
    qs = services.owned_queryset(Event, request.user, scope__code=Scope.WORK)
    if filters["project"]:
        qs = qs.filter(project_id=filters["project"])
    if filters["priority"]:
        qs = qs.filter(priority=filters["priority"])
    if filters["tag"]:
        qs = qs.filter(tags__contains=[filters["tag"]])
    if filters["q"]:
        term = filters["q"]
        qs = qs.filter(Q(title__icontains=term) | Q(description__icontains=term))
    return qs


@login_required
def work_board(request):
    services.ensure_statuses(request.user, services.get_scope(request.user, Scope.WORK))
    filters = _kanban_filters(request)
    statuses = list(Status.objects.filter(user=request.user, is_deleted=False).order_by("sort_order"))
    events = _work_queryset(request, filters).select_related("project", "status").prefetch_related("comments")

    columns = []
    for st in statuses:
        cards = [e for e in events if e.status_id == st.id]
        columns.append({"status": st, "cards": cards})
    no_status = [e for e in events if e.status_id is None]
    if no_status:
        columns.append({"status": None, "cards": no_status})

    all_tags = sorted({tag for e in events for tag in (e.tags or [])})
    context = _ctx(
        request,
        columns=columns,
        filters=filters,
        pl_no_status=t("pl.no_status"),
        projects=_user_projects(request.user, Scope.WORK),
        all_tags=all_tags,
        priorities=Event.PRIORITIES,
        today=timezone.localdate(),
    )
    return render(request, "planner/work_board.html", context)


@login_required
def task_create(request):
    services.ensure_statuses(request.user, services.get_scope(request.user, Scope.WORK))
    form = TaskForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_task_saved"))
        return redirect("planner:work")
    context = _ctx(request, form=form, is_new=True)
    return render(request, "planner/task_form.html", context)


@login_required
def task_update(request, pk):
    task = get_object_or_404(Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK)
    form = TaskForm(request.user, request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_task_saved"))
        return redirect("planner:task", pk=pk)
    context = _ctx(request, form=form, task=task, is_new=False)
    return render(request, "planner/task_form.html", context)


@login_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(
        Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK
    )
    task.delete()
    messages.success(request, t("pl.msg_task_deleted"))
    return redirect("planner:work")


@login_required
@require_POST
def task_move(request, pk):
    """Drag-n-drop Kanban: перенос карточки в статус (HTMX)."""
    task = get_object_or_404(Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK)
    to_status = request.POST.get("to_status") or None
    if to_status == "__none__":
        to_status = None
    status = None
    if to_status:
        status = get_object_or_404(Status, pk=to_status, user=request.user, is_deleted=False)
    services.change_event_status(task, status, request.user)
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect("planner:work")


@login_required
def task_detail(request, pk):
    task = get_object_or_404(
        Event.objects.select_related("project", "status"),
        pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK,
    )
    comments = task.comments.filter(is_deleted=False).prefetch_related("attachments")
    history = task.status_history.select_related("from_status", "to_status", "changed_by")
    statuses = Status.objects.filter(user=request.user, is_deleted=False).order_by("sort_order")
    comment_form = CommentForm(request.user)
    context = _ctx(
        request, task=task, comments=comments, history=history,
        statuses=statuses, form=comment_form,
        projects=_user_projects(request.user, Scope.WORK),
    )
    return render(request, "planner/task_detail.html", context)


def _reload_response():
    """Ответ для AJAX-панели: закрыть slide-over и обновить страницу."""
    return HttpResponse("<script>location.reload()</script>", content_type="text/html")


@login_required
@require_POST
def comment_add(request, pk):
    task = get_object_or_404(Event, pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK)
    form = CommentForm(request.user, request.POST or None, request.FILES or None)
    if form.is_valid():
        services.create_comment(request.user, task, form.cleaned_data["text"], form.cleaned_data["files"])
        if request.headers.get("HX-Request"):
            return _reload_response()
        return redirect("planner:task", pk=pk)
    for errors in form.errors.values():
        for err in errors:
            messages.error(request, str(err))
    return redirect("planner:task", pk=pk)


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk, user=request.user, is_deleted=False)
    task_pk = comment.event_id
    comment.delete()
    if request.headers.get("HX-Request"):
        return _reload_response()
    return redirect("planner:task", pk=task_pk)


@login_required
def task_panel(request, pk):
    """Боковая панель карточки задачи (slide-over, макет 19)."""
    task = get_object_or_404(
        Event.objects.select_related("project", "status"),
        pk=pk, user=request.user, is_deleted=False, scope__code=Scope.WORK,
    )
    context = {
        "task": task,
        "comments": task.comments.filter(is_deleted=False).prefetch_related("attachments"),
        "history": task.status_history.select_related("from_status", "to_status", "changed_by"),
        "statuses": Status.objects.filter(user=request.user, is_deleted=False).order_by("sort_order"),
        "form": CommentForm(request.user),
        "today": timezone.localdate(),
    }
    return render(request, "planner/partials/_task_panel.html", context)


# ------------------------------------------------------------------
# Проекты (макет 20)
# ------------------------------------------------------------------

@login_required
def project_list(request):
    scope_code = request.GET.get("scope", "")
    qs = services.owned_queryset(Project, request.user).select_related("scope")
    if scope_code in {Scope.PERSONAL, Scope.WORK}:
        qs = qs.filter(scope__code=scope_code)
    projects = list(qs.order_by("is_archived", "title"))
    ids = [p.pk for p in projects]
    stats = {
        row["project"]: row
        for row in Event.objects.filter(
            user=request.user, is_deleted=False, project_id__in=ids
        ).values("project").annotate(
            total=Count("id"),
            done=Count("id", filter=Q(status__code="done")),
        )
    }
    for p in projects:
        row = stats.get(p.pk)
        p.events_total = row["total"] if row else 0
        p.progress = (
            round(row["done"] * 100 / row["total"])
            if row and row["total"] and p.scope.code == Scope.WORK
            else (0 if row and p.scope.code == Scope.WORK else None)
        )
    context = _ctx(
        request,
        projects=projects,
        scope_code=scope_code,
    )
    return render(request, "planner/project_list.html", context)


@login_required
def project_create(request):
    form = ProjectForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_project_saved"))
        return redirect("planner:projects")
    context = _ctx(request, form=form, is_new=True, **_project_form_ctx())
    return render(request, "planner/project_form.html", context)


@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk, user=request.user, is_deleted=False)
    form = ProjectForm(request.user, request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_project_saved"))
        return redirect("planner:projects")
    context = _ctx(request, form=form, project=project, is_new=False, **_project_form_ctx())
    return render(request, "planner/project_form.html", context)


def _project_form_ctx():
    return {"preset_colors": Project.PRESET_COLORS, "pl_projects_word": t("pl.projects")}


@login_required
@require_POST
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk, user=request.user, is_deleted=False)
    project.delete()
    messages.success(request, t("pl.msg_project_deleted"))
    return redirect("planner:projects")


@login_required
@require_POST
def project_toggle_archive(request, pk):
    project = get_object_or_404(Project, pk=pk, user=request.user, is_deleted=False)
    project.is_archived = not project.is_archived
    project.save(update_fields=["is_archived", "updated_at"])
    messages.success(request, t("pl.msg_project_archived" if project.is_archived else "pl.msg_project_restored"))
    return redirect("planner:projects")


# ------------------------------------------------------------------
# Настройка статусов (макет 21)
# ------------------------------------------------------------------

@login_required
def status_list(request):
    services.ensure_statuses(request.user, services.get_scope(request.user, Scope.WORK))
    statuses = Status.objects.filter(user=request.user, is_deleted=False).order_by("sort_order")
    counts = dict(
        Event.objects.filter(user=request.user, is_deleted=False, scope__code=Scope.WORK)
        .values_list("status")
        .annotate(c=Count("id"))
    )
    rows = []
    for st in statuses:
        rows.append({"status": st, "tasks": counts.get(st.id, 0)})
    context = _ctx(request, rows=rows)
    return render(request, "planner/status_list.html", context)


@login_required
@require_POST
def status_create(request):
    name = (request.POST.get("name") or "").strip()
    color = (request.POST.get("color") or "#94A3B8").strip()
    if not name:
        messages.error(request, t("pl.err_status_name"))
        return redirect("planner:statuses")
    last = Status.objects.filter(user=request.user, is_deleted=False).order_by("-sort_order").first()
    code = f"custom_{(last.sort_order + 1 if last else 0) + 1}"
    while Status.objects.filter(user=request.user, code=code).exists():
        code += "x"
    Status.objects.create(
        user=request.user, code=code, name=name, color=color,
        sort_order=(last.sort_order + 1 if last else 0), is_system=False,
    )
    messages.success(request, t("pl.msg_status_saved"))
    return redirect("planner:statuses")


@login_required
@require_POST
def status_update(request, pk):
    status = get_object_or_404(Status, pk=pk, user=request.user, is_deleted=False)
    form = StatusForm(request.user, request.POST or None, instance=status)
    if form.is_valid():
        form.save()
        messages.success(request, t("pl.msg_status_saved"))
    return redirect("planner:statuses")


@login_required
@require_POST
def status_delete(request, pk):
    status = get_object_or_404(Status, pk=pk, user=request.user, is_deleted=False)
    used = Event.objects.filter(user=request.user, is_deleted=False, status=status).exists()
    if used:
        messages.error(request, t("pl.err_status_in_use"))
    else:
        status.delete()
        messages.success(request, t("pl.msg_status_deleted"))
    return redirect("planner:statuses")


@login_required
@require_POST
def status_reorder(request):
    order = request.POST.getlist("order")
    for idx, pk in enumerate(order):
        Status.objects.filter(user=request.user, pk=pk, is_deleted=False).update(
            sort_order=idx, updated_at=timezone.now()
        )
    return JsonResponse({"ok": True})


# ------------------------------------------------------------------
# Поиск (ТЗ 4.3.2/4.3.3)
# ------------------------------------------------------------------

@login_required
def planner_search(request):
    q = (request.GET.get("q") or "").strip()
    scope = request.GET.get("scope", "")
    results = services.search_events(request.user, scope or None, q) if q else []
    context = _ctx(request, q=q, scope=scope, results=results)
    return render(request, "planner/planner_search.html", context)
