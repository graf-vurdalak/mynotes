"""Unit-тесты Записной книжки (Этап 3): скоупы, события, Kanban, статусы,
проекты, повторы, поиск, IDOR и страницы."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.planner import services
from apps.planner.models import Comment, Event, Project, Scope, Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user(email="pl@test.local", password="pass12345")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="other@test.local", password="pass12345")


@pytest.fixture
def scopes(user):
    return services.guarantee_scopes(user)


@pytest.fixture
def personal(user, scopes):
    return services.get_scope(user, Scope.PERSONAL)


@pytest.fixture
def work(user, scopes):
    scope = services.get_scope(user, Scope.WORK)
    services.ensure_statuses(user, scope)
    return scope


def make_client(client, user):
    client.force_login(user)
    return client


# ------------------------------------------------------------------
# Скоупы и IDOR
# ------------------------------------------------------------------

def test_guarantee_scopes_idempotent(user):
    first = services.guarantee_scopes(user)
    second = services.guarantee_scopes(user)
    assert first["personal"].pk == second["personal"].pk
    assert Scope.objects.filter(user=user).count() == 2


def test_scope_isolation_between_users(user, other_user):
    services.guarantee_scopes(user)
    services.guarantee_scopes(other_user)
    assert Scope.objects.exclude(user=user).exclude(user=other_user).count() == 0
    qs = services.owned_queryset(Scope, user)
    assert qs.count() == 2
    assert all(s.user_id == user.pk for s in qs)


def test_ensure_statuses_creates_five_system(user, work):
    statuses = Status.objects.filter(user=user, is_deleted=False)
    assert statuses.count() == 5
    assert list(statuses.order_by("sort_order").values_list("code", flat=True)) == [
        "new", "estimate", "in_progress", "testing", "done",
    ]
    services.ensure_statuses(user, work)
    assert Status.objects.filter(user=user).count() == 5


# ------------------------------------------------------------------
# События личного раздела
# ------------------------------------------------------------------

def test_create_personal_event_via_form(client, user, personal):
    make_client(client, user)
    resp = client.post("/planner/personal/event/new/", {
        "title": "Встреча с врачом",
        "description": "Поликлиника",
        "date_start": "2026-10-05",
        "time_start": "09:00",
        "date_end": "2026-10-05",
        "time_end": "10:00",
        "location": "Поликлиника №1",
        "priority": "high",
        "tags": "здоровье, визит",
        "recurrence": "",
        "reminder_enabled": "on",
        "reminder_minutes": 60,
    })
    assert resp.status_code == 302
    event = Event.objects.get(user=user, title="Встреча с врачом")
    assert event.scope.code == "personal"
    assert event.location == "Поликлиника №1"
    assert event.priority == "high"
    assert set(event.tags) == {"здоровье", "визит"}
    assert event.reminder_minutes_before == 60
    assert event.start_at.year == 2026 and event.start_at.month == 10


def test_event_soft_delete(user, personal):
    e = Event.objects.create(user=user, scope=personal, title="X")
    e.delete()
    e.refresh_from_db()
    assert e.is_deleted is True


def test_event_page_requires_login(client):
    assert client.get("/planner/personal/").status_code == 302


def test_event_idor_other_user_cannot_edit(client, user, other_user, personal):
    e = Event.objects.create(user=user, scope=personal, title="Чужое")
    make_client(client, other_user)
    assert client.get(f"/planner/personal/event/{e.pk}/edit/").status_code == 404
    assert client.post(f"/planner/personal/event/{e.pk}/delete/").status_code == 404


# ------------------------------------------------------------------
# Kanban и статусы
# ------------------------------------------------------------------

def test_change_event_status_writes_history(user, work):
    st_new = Status.objects.get(user=user, code="new")
    st_done = Status.objects.get(user=user, code="done")
    task = Event.objects.create(user=user, scope=work, title="Задача", status=st_new)
    services.change_event_status(task, st_done, user)
    task.refresh_from_db()
    assert task.status == st_done
    assert task.completed_at is not None
    history = task.status_history.get()
    assert history.from_status == st_new and history.to_status == st_done
    # повторная смена на тот же статус — без дубля записи
    services.change_event_status(task, st_done, user)
    assert task.status_history.count() == 1
    # откат из done сбрасывает completed_at
    services.change_event_status(task, st_new, user)
    task.refresh_from_db()
    assert task.completed_at is None


def test_kanban_move_endpoint(client, user, work):
    st_new = Status.objects.get(user=user, code="new")
    st_prog = Status.objects.get(user=user, code="in_progress")
    task = Event.objects.create(user=user, scope=work, title="T", status=st_new)
    make_client(client, user)
    resp = client.post(f"/planner/work/task/{task.pk}/move/", {"to_status": str(st_prog.pk)})
    assert resp.status_code == 302
    task.refresh_from_db()
    assert task.status == st_prog


def test_kanban_move_idor(client, user, other_user, work):
    st = Status.objects.get(user=user, code="new")
    task = Event.objects.create(user=user, scope=work, title="T", status=st)
    make_client(client, other_user)
    resp = client.post(f"/planner/work/task/{task.pk}/move/", {"to_status": str(st.pk)})
    assert resp.status_code == 404


def test_status_create_and_delete(client, user, work):
    make_client(client, user)
    resp = client.post("/planner/work/statuses/new/", {"name": "На доработке", "color": "#8B5CF6"})
    assert resp.status_code == 302
    custom = Status.objects.get(user=user, name="На доработке")
    assert custom.is_system is False
    # удаление пустого пользовательского статуса
    assert client.post(f"/planner/work/statuses/{custom.pk}/delete/").status_code == 302
    custom.refresh_from_db()
    assert custom.is_deleted is True
    # системный статус с задачами удалить нельзя
    st_new = Status.objects.get(user=user, code="new")
    Event.objects.create(user=user, scope=work, title="Z", status=st_new)
    client.post(f"/planner/work/statuses/{st_new.pk}/delete/")
    st_new.refresh_from_db()
    assert st_new.is_deleted is False


def test_comment_add_and_delete(client, user, work):
    task = Event.objects.create(user=user, scope=work, title="T")
    make_client(client, user)
    resp = client.post(f"/planner/work/task/{task.pk}/comment/", {"text": "Готовлю фикс"})
    assert resp.status_code == 302
    comment = Comment.objects.get(event=task, text="Готовлю фикс")
    assert comment.author == user
    client.post(f"/planner/work/comment/{comment.pk}/delete/")
    comment.refresh_from_db()
    assert comment.is_deleted is True


# ------------------------------------------------------------------
# Проекты
# ------------------------------------------------------------------

def test_project_progress(user, work, personal):
    project = Project.objects.create(user=user, scope=work, title="Бэкенд")
    st_done = Status.objects.get(user=user, code="done")
    st_new = Status.objects.get(user=user, code="new")
    Event.objects.create(user=user, scope=work, title="A", project=project, status=st_done)
    Event.objects.create(user=user, scope=work, title="B", project=project, status=st_new)
    Event.objects.create(user=user, scope=work, title="C", project=project, status=st_new)
    Event.objects.create(user=user, scope=work, title="D", project=project, status=st_new)
    assert services.project_progress(project) == 25
    personal_project = Project.objects.create(user=user, scope=personal, title="Дом")
    assert services.project_progress(personal_project) is None


def test_project_archive_toggle(client, user, personal):
    p = Project.objects.create(user=user, scope=personal, title="Ремонт")
    make_client(client, user)
    client.post(f"/planner/projects/{p.pk}/archive/")
    p.refresh_from_db()
    assert p.is_archived is True
    client.post(f"/planner/projects/{p.pk}/archive/")
    p.refresh_from_db()
    assert p.is_archived is False


# ------------------------------------------------------------------
# Повторяющиеся события
# ------------------------------------------------------------------

def _aware(d):
    return timezone.make_aware(dt.datetime.combine(d, dt.time(8, 0)))


def test_expand_daily(user, personal):
    e = Event.objects.create(
        user=user, scope=personal, title="Зарядка",
        start_at=_aware(dt.date(2026, 10, 1)), recurrence_rule="daily",
    )
    occ = services.expand_recurring(e, dt.date(2026, 10, 1), dt.date(2026, 10, 7))
    assert len(occ) == 7
    assert occ[0].date() == dt.date(2026, 10, 1)


def test_expand_weekly_with_count(user, personal):
    e = Event.objects.create(
        user=user, scope=personal, title="Созвон",
        start_at=_aware(dt.date(2026, 10, 5)), recurrence_rule="weekly", recurrence_count=3,
    )
    occ = services.expand_recurring(e, dt.date(2026, 10, 1), dt.date(2026, 12, 31))
    assert [o.date() for o in occ] == [
        dt.date(2026, 10, 5), dt.date(2026, 10, 12), dt.date(2026, 10, 19),
    ]


def test_expand_byday(user, personal):
    e = Event.objects.create(
        user=user, scope=personal, title="Тренировка",
        start_at=_aware(dt.date(2026, 10, 5)), recurrence_rule="weekly:BYDAY=MO,WE",
    )
    occ = services.expand_recurring(e, dt.date(2026, 10, 5), dt.date(2026, 10, 14))
    assert [o.date() for o in occ] == [
        dt.date(2026, 10, 5), dt.date(2026, 10, 7), dt.date(2026, 10, 12), dt.date(2026, 10, 14),
    ]


def test_expand_monthly_respects_end(user, personal):
    e = Event.objects.create(
        user=user, scope=personal, title="Аренда",
        start_at=_aware(dt.date(2026, 1, 31)), recurrence_rule="monthly",
        recurrence_end=timezone.make_aware(dt.datetime(2026, 4, 1)),
    )
    occ = services.expand_recurring(e, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    # 31 января, 28 февраля (fallback), 31 марта — до 1 апреля включительно
    assert [o.date() for o in occ] == [
        dt.date(2026, 1, 31), dt.date(2026, 2, 28), dt.date(2026, 3, 31),
    ]


def test_events_for_range_includes_regular_and_recurring(user, personal):
    Event.objects.create(
        user=user, scope=personal, title="Разовое", start_at=_aware(dt.date(2026, 10, 3)),
    )
    Event.objects.create(
        user=user, scope=personal, title="Повтор", start_at=_aware(dt.date(2026, 10, 1)),
        recurrence_rule="daily",
    )
    items = services.events_for_range(user, Scope.PERSONAL, dt.date(2026, 10, 1), dt.date(2026, 10, 3))
    titles = [i["event"].title for i in items]
    assert titles.count("Повтор") == 3
    assert "Разовое" in titles
    assert all(i["start"] for i in items)


# ------------------------------------------------------------------
# Поиск
# ------------------------------------------------------------------

def test_search_events(user, personal, work):
    Event.objects.create(user=user, scope=personal, title="Купить билеты", tags=["поездка"])
    Event.objects.create(user=user, scope=work, title="Отчёт по биллингу", description="детали")
    assert services.search_events(user, None, "бил").count() == 2
    assert services.search_events(user, Scope.WORK, "бил").count() == 1
    assert services.search_events(user, None, "поездка").count() == 1
    assert services.search_events(user, None, "").count() == 0


def test_search_page_renders(client, user, personal):
    Event.objects.create(user=user, scope=personal, title="Стоматолог")
    make_client(client, user)
    resp = client.get("/planner/search/", {"q": "стома"})
    assert resp.status_code == 200
    assert "Стоматолог" in resp.content.decode()


# ------------------------------------------------------------------
# Регрессии code-review (этап 3)
# ------------------------------------------------------------------

def test_recurrence_weekdays_and_interval_no_crash(client, user, personal):
    make_client(client, user)
    resp = client.post("/planner/personal/event/new/", {
        "title": "Тренировка",
        "date_start": "2026-10-05",
        "time_start": "08:00",
        "priority": "normal",
        "recurrence": "weekdays",
        "recurrence_byday": ["MO", "WE"],
    })
    assert resp.status_code == 302
    e = Event.objects.get(user=user, title="Тренировка")
    assert e.recurrence_rule == "weekly:BYDAY=MO,WE"
    resp = client.post("/planner/personal/event/new/", {
        "title": "Интервальный",
        "date_start": "2026-10-05",
        "priority": "normal",
        "recurrence": "interval",
        "recurrence_interval": "3",
        "recurrence_count": "5",
        "recurrence_until": "2026-12-31",
    })
    assert resp.status_code == 302
    e = Event.objects.get(user=user, title="Интервальный")
    assert e.recurrence_rule == "FREQ=DAILY;INTERVAL=3"
    assert e.recurrence_count == 5
    assert e.recurrence_end is not None


def test_recurrence_weekdays_requires_day(client, user, personal):
    make_client(client, user)
    resp = client.post("/planner/personal/event/new/", {
        "title": "Без дней",
        "date_start": "2026-10-05",
        "recurrence": "weekdays",
    })
    assert resp.status_code == 200  # без 500, форма с ошибкой
    assert not Event.objects.filter(user=user, title="Без дней").exists()


def test_reminder_semantics(client, user, personal):
    make_client(client, user)
    base = {
        "title": "R", "date_start": "2026-10-05", "time_start": "09:00", "priority": "normal",
    }
    # выключенное напоминание = 0 (не глобальный дефолт)
    client.post("/planner/personal/event/new/", dict(base, title="R-off"))
    assert Event.objects.get(user=user, title="R-off").reminder_minutes_before == 0
    # включённое без минут = None (глобальный дефолт)
    client.post("/planner/personal/event/new/", dict(base, title="R-def", reminder_enabled="on"))
    assert Event.objects.get(user=user, title="R-def").reminder_minutes_before is None
    # включённое с минутами
    client.post("/planner/personal/event/new/", dict(base, title="R-60", reminder_enabled="on", reminder_minutes="60"))
    assert Event.objects.get(user=user, title="R-60").reminder_minutes_before == 60


def test_cross_scope_delete_is_404(client, user, personal, work):
    personal_event = Event.objects.create(user=user, scope=personal, title="Личное")
    work_task = Event.objects.create(user=user, scope=work, title="Рабочее")
    make_client(client, user)
    assert client.post(f"/planner/work/task/{personal_event.pk}/delete/").status_code == 404
    assert client.post(f"/planner/personal/event/{work_task.pk}/delete/").status_code == 404
    personal_event.refresh_from_db()
    work_task.refresh_from_db()
    assert not personal_event.is_deleted and not work_task.is_deleted


def test_open_redirect_blocked(client, user, personal):
    make_client(client, user)
    resp = client.post(
        "/planner/personal/event/new/",
        {
            "title": "Safe", "date_start": "2026-10-05", "time_start": "09:00",
            "priority": "normal", "next": "https://evil.example.com/phish",
        },
    )
    assert resp.status_code == 302
    assert resp.url == "/planner/personal/"  # noqa: B023 (fallback, не внешний хост)


def test_comment_upload_rejects_oversize_and_html(client, user, work):
    from django.core.files.uploadedfile import SimpleUploadedFile

    task = Event.objects.create(user=user, scope=work, title="T")
    make_client(client, user)
    big = SimpleUploadedFile("big.bin", b"x" * (10 * 1024 * 1024 + 10), content_type="application/octet-stream")
    resp = client.post(f"/planner/work/task/{task.pk}/comment/", {"text": "файл", "files": big})
    assert resp.status_code == 302
    assert not task.attachments.exists()
    html = SimpleUploadedFile("x.html", b"<script>alert(1)</script>", content_type="text/html")
    client.post(f"/planner/work/task/{task.pk}/comment/", {"text": "html", "files": html})
    assert not task.attachments.exists()
    ok = SimpleUploadedFile("ok.txt", b"plain text", content_type="text/plain")
    client.post(f"/planner/work/task/{task.pk}/comment/", {"text": "норм", "files": ok})
    att = task.attachments.get()
    assert att.mime_type == "text/plain" and att.size_bytes == 10


def test_upcoming_excludes_past(client, user, personal):
    make_client(client, user)
    Event.objects.create(
        user=user, scope=personal, title="Вчера",
        start_at=timezone.now() - dt.timedelta(days=1),
    )
    items = services.upcoming_events(user, Scope.PERSONAL, limit=5)
    assert all(i["start"] >= timezone.now() for i in items)
    assert "Вчера" not in [i["event"].title for i in items]


def test_expand_old_daily_still_visible(user, personal):
    e = Event.objects.create(
        user=user, scope=personal, title="Древнее",
        start_at=_aware(dt.date(2020, 1, 1)), recurrence_rule="daily",
    )
    occ = services.expand_recurring(e, dt.date(2026, 10, 1), dt.date(2026, 10, 3))
    assert len(occ) == 3  # cap не режет давние повторы


def test_events_for_range_db_filters_history(user, personal):
    Event.objects.create(user=user, scope=personal, title="Давно", start_at=_aware(dt.date(2020, 1, 1)))
    Event.objects.create(user=user, scope=personal, title="Сейчас", start_at=_aware(dt.date(2026, 10, 2)))
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        items = services.events_for_range(user, Scope.PERSONAL, dt.date(2026, 10, 1), dt.date(2026, 10, 3))
    titles = [i["event"].title for i in items]
    assert "Давно" not in titles and "Сейчас" in titles
    sql = " ".join(q["sql"] for q in ctx.captured_queries)
    assert "planner_event" in sql


def test_day_view_renders(client, user, personal):
    Event.objects.create(user=user, scope=personal, title="Йога-день", start_at=_aware(dt.date(2026, 10, 10)))
    make_client(client, user)
    resp = client.get("/planner/personal/", {"view": "day", "date": "2026-10-10"})
    assert resp.status_code == 200
    assert "Йога-день" in resp.content.decode()


def test_night_event_lands_local_day(client, user, personal):
    # 00:30 Europe/Moscow = 21:30 UTC предыдущего дня — ячейка по локальной дате
    night = timezone.make_aware(
        dt.datetime.combine(dt.date(2026, 10, 10), dt.time(0, 30)), timezone.get_current_timezone()
    )
    Event.objects.create(user=user, scope=personal, title="Полночь", start_at=night)
    make_client(client, user)
    resp = client.get("/planner/personal/", {"date": "2026-10-10", "selected": "2026-10-10"})
    assert "Полночь" in resp.content.decode()


def test_task_recurrence_bounds_saved(client, user, work):
    make_client(client, user)
    resp = client.post("/planner/work/task/new/", {
        "title": "Регламент",
        "priority": "normal",
        "recurrence": "weekly",
        "recurrence_until": "2026-12-31",
        "recurrence_count": "10",
    })
    assert resp.status_code == 302
    t = Event.objects.get(user=user, title="Регламент")
    assert t.recurrence_rule == "weekly"
    assert t.recurrence_count == 10 and t.recurrence_end is not None


# ------------------------------------------------------------------
# Страницы (smoke)
# ------------------------------------------------------------------

def test_event_form_page_renders(client, user, personal):
    make_client(client, user)
    resp = client.get("/planner/personal/event/new/")
    assert resp.status_code == 200
    e = Event.objects.create(user=user, scope=personal, title="Сущ", start_at=_aware(dt.date(2026, 10, 10)))
    resp = client.get(f"/planner/personal/event/{e.pk}/edit/")
    assert resp.status_code == 200


def test_scope_picker_page(client, user):
    make_client(client, user)
    resp = client.get("/planner/")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Личное" in content and "Рабочее" in content


def test_personal_calendar_page(client, user, personal):
    Event.objects.create(
        user=user, scope=personal, title="Йога", start_at=_aware(dt.date(2026, 10, 10)),
    )
    make_client(client, user)
    resp = client.get("/planner/personal/", {"date": "2026-10-10"})
    assert resp.status_code == 200
    assert "Йога" in resp.content.decode()


def test_work_board_page(client, user, work):
    st = Status.objects.get(user=user, code="new")
    Event.objects.create(user=user, scope=work, title="Фича", status=st)
    make_client(client, user)
    resp = client.get("/planner/work/")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Фича" in content and "Новый" in content
    assert "Sortable" in content


def test_task_detail_page(client, user, work):
    st = Status.objects.get(user=user, code="new")
    task = Event.objects.create(user=user, scope=work, title="Баг", status=st)
    Comment.objects.create(user=user, author=user, event=task, text="Коммент")
    make_client(client, user)
    resp = client.get(f"/planner/work/task/{task.pk}/")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Баг" in content and "Коммент" in content


def test_projects_page(client, user, personal):
    Project.objects.create(user=user, scope=personal, title="Сад")
    make_client(client, user)
    resp = client.get("/planner/projects/")
    assert resp.status_code == 200
    assert "Сад" in resp.content.decode()


def test_statuses_page(client, user, work):
    make_client(client, user)
    resp = client.get("/planner/work/statuses/")
    assert resp.status_code == 200
    assert "Оценка" in resp.content.decode()


def test_feed_page(client, user, personal):
    Event.objects.create(
        user=user, scope=personal, title="Дентист",
        start_at=timezone.now() + dt.timedelta(days=2),
    )
    make_client(client, user)
    resp = client.get("/planner/personal/feed/")
    assert resp.status_code == 200
    assert "Дентист" in resp.content.decode()
