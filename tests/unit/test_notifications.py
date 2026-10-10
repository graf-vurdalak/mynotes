# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import User, UserSettings
from apps.accounts.tokens import issue_token
from apps.notifications.models import BotChatBinding, Notification
from apps.notifications.services import bind_chat, notify
from apps.notifications.tasks import scan_event_reminders, scan_vehicle_reminders
from apps.notifications.telegram import send_telegram
from apps.planner.models import Event, Scope
from apps.planner.services import get_scope
from apps.vehicles.models import Fine, Insurance, PlannedEvent, Vehicle


@pytest.fixture
def user(db):
    return User.objects.create_user(email="notif@test.ru", password="pass12345")


@pytest.mark.django_db
def test_notify_creates_and_sends_email(user):
    n = notify(user, "test.type", "Заголовок", "Тело", channels=("email",))
    assert n is not None
    assert n.is_read is False
    assert n.sent_via_email is True
    assert n.sent_via_telegram is False
    assert len(mail_outbox(user)) == 1


@pytest.mark.django_db
def test_notify_email_failure_keeps_record(user, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("apps.notifications.services.EmailMessage", boom)
    n = notify(user, "test.fail", "Т", "М", channels=("email",))
    assert n is not None
    assert n.sent_via_email is False


@pytest.mark.django_db
def test_notify_dedup_within_window(user):
    first = notify(user, "fine.unpaid", "Штрафы", channels=(), dedup_within=timedelta(days=1))
    second = notify(user, "fine.unpaid", "Штрафы", channels=(), dedup_within=timedelta(days=1))
    assert first is not None
    assert second is None
    assert Notification.objects.filter(user=user, type="fine.unpaid").count() == 1


@pytest.mark.django_db
def test_notify_dedup_window_expires(user):
    with freeze_time("2026-10-01 09:00:00"):
        notify(user, "fine.unpaid", "Штрафы", channels=(), dedup_within=timedelta(days=1))
    with freeze_time("2026-10-03 09:00:00"):
        again = notify(user, "fine.unpaid", "Штрафы", channels=(), dedup_within=timedelta(days=1))
        assert again is not None
    assert Notification.objects.filter(user=user, type="fine.unpaid").count() == 2


@pytest.mark.django_db
def test_notify_dedup_scoped_by_entity(user):
    vehicle = Vehicle.objects.create(user=user, current_mileage=10000, is_default=True)
    i1 = Insurance.objects.create(user=user, vehicle=vehicle, company="А", end_date="2026-11-01")
    i2 = Insurance.objects.create(user=user, vehicle=vehicle, company="Б", end_date="2026-11-01")
    n1 = notify(user, "insurance.expiring", "Т", entity=i1, channels=(), dedup_within=timedelta(days=1))
    n2 = notify(user, "insurance.expiring", "Т", entity=i2, channels=(), dedup_within=timedelta(days=1))
    assert n1 is not None and n2 is not None
    assert n1.entity_type == "vehicles.insurance"
    assert str(n1.entity_id) == str(i1.pk)


@pytest.mark.django_db
def test_notify_entity_optional_fields(user):
    n = notify(user, "plain", "Т", channels=())
    assert n.entity_type == ""
    assert n.entity_id is None


@pytest.mark.django_db
def test_notification_ordering_and_str(user):
    older = notify(user, "a", "Первое", channels=())
    newer = notify(user, "b", "Второе", channels=())
    assert list(Notification.objects.all()) == [newer, older]
    assert str(newer) == "b: Второе"


def mail_outbox(user):
    from django.core import mail

    return [m for m in mail.outbox if user.email in m.to]


# --- 5.2: привязка чата и Telegram-канал ----------------------------------

@pytest.mark.django_db
def test_bind_chat_creates_and_updates(user):
    b = bind_chat(user, "vehicle", "111")
    assert b is not None and b.chat_id == "111"
    b2 = bind_chat(user, "vehicle", "222")
    assert b2.pk == b.pk and b2.chat_id == "222"
    bind_chat(user, "planner", "333")
    assert BotChatBinding.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_bind_chat_rejects_garbage(user):
    assert bind_chat(user, "vehicle", "abc-12") is None
    assert bind_chat(user, "telegram", "123") is None
    assert bind_chat(user, "vehicle", "") is None
    assert BotChatBinding.objects.count() == 0


@pytest.mark.django_db
def test_gateway_upserts_binding_from_headers(client, user):
    plain, _ = issue_token(user, "тест")
    r = client.post(
        "/api/v1/bot/ping/",
        HTTP_X_BOT_TOKEN=plain,
        HTTP_X_BOT_NAME="planner",
        HTTP_X_TELEGRAM_CHAT_ID="42",
    )
    assert r.status_code == 200
    binding = BotChatBinding.objects.get(user=user, bot="planner")
    assert binding.chat_id == "42"
    # без заголовков — ничего не создаётся и не падает
    assert client.post("/api/v1/bot/ping/", HTTP_X_BOT_TOKEN=plain).status_code == 200
    assert BotChatBinding.objects.filter(user=user).count() == 1


@override_settings(
    TELEGRAM_VEHICLE_BOT_TOKEN="123:secret",
    TELEGRAM_PLANNER_BOT_TOKEN="",
    TELEGRAM_HTTP_PROXY="",
)
@pytest.mark.django_db
def test_send_telegram_success(user, monkeypatch):
    bind_chat(user, "vehicle", "42")
    post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}, text=""))
    monkeypatch.setattr("apps.notifications.telegram.requests.post", post)
    n = notify(user, "vehicle.any", "Заголовок", "Текст", channels=("telegram",))
    assert n.sent_via_telegram is True
    assert post.call_args.args[0].endswith("/sendMessage")
    assert post.call_args.kwargs["json"] == {"chat_id": "42", "text": "Заголовок\nТекст"}
    assert "proxies" not in post.call_args.kwargs


@override_settings(
    TELEGRAM_VEHICLE_BOT_TOKEN="123:secret",
    TELEGRAM_HTTP_PROXY="http://172.29.172.1:3128",
)
@pytest.mark.django_db
def test_send_telegram_uses_configured_proxy(user, monkeypatch):
    bind_chat(user, "vehicle", "42")
    post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}, text=""))
    monkeypatch.setattr("apps.notifications.telegram.requests.post", post)

    n = notify(user, "vehicle.any", "Заголовок", "Текст", channels=("telegram",))

    assert n.sent_via_telegram is True
    assert post.call_args.kwargs["proxies"] == {"https": "http://172.29.172.1:3128"}


@override_settings(TELEGRAM_VEHICLE_BOT_TOKEN="")
@pytest.mark.django_db
def test_send_telegram_no_token_skips(user, monkeypatch):
    bind_chat(user, "vehicle", "42")
    post = MagicMock()
    monkeypatch.setattr("apps.notifications.telegram.requests.post", post)
    n = notify(user, "vehicle.any", "Т", "М", channels=("telegram",))
    assert n.sent_via_telegram is False
    post.assert_not_called()


@override_settings(TELEGRAM_VEHICLE_BOT_TOKEN="123:secret")
@pytest.mark.django_db
def test_send_telegram_no_binding_skips(user, monkeypatch):
    post = MagicMock()
    monkeypatch.setattr("apps.notifications.telegram.requests.post", post)
    assert send_telegram(user, MagicMock(entity_type="vehicles.insurance",
                                         type="insurance.expiring", pk=0, title="", message=""),
                         bot=None) is False
    post.assert_not_called()


@pytest.mark.django_db
def test_send_telegram_http_error_is_swallowed(user, monkeypatch):
    import requests as _rq

    bind_chat(user, "vehicle", "42")
    monkeypatch.setattr("apps.notifications.telegram.requests.post",
                        MagicMock(side_effect=_rq.ConnectionError("down")))
    with override_settings(TELEGRAM_VEHICLE_BOT_TOKEN="123:secret"):
        n = notify(user, "vehicle.any", "Т", "М", channels=("telegram",))
    assert n is not None and n.sent_via_telegram is False


@pytest.mark.django_db
def test_notify_derives_bot_from_entity(user, monkeypatch):
    vehicle = Vehicle.objects.create(user=user, current_mileage=1, is_default=True)
    i = Insurance.objects.create(user=user, vehicle=vehicle, company="А", end_date="2026-11-01")
    post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}, text=""))
    monkeypatch.setattr("apps.notifications.telegram.requests.post", post)
    with override_settings(TELEGRAM_VEHICLE_BOT_TOKEN="123:secret", TELEGRAM_PLANNER_BOT_TOKEN=""):
        bind_chat(user, "vehicle", "7")
        n = notify(user, "insurance.expiring", "Т", entity=i, channels=("telegram",))
    assert n.sent_via_telegram is True
    assert post.call_args.args[0].endswith("/sendMessage")


# --- 5.3: scan_event_reminders (ТЗ 4.3.5) ---------------------------------

@pytest.fixture
def personal(user):
    return get_scope(user, Scope.PERSONAL)


def _mk_event(user, scope, start, **kw):
    return Event.objects.create(user=user, scope=scope, title="Созвон", start_at=start, **kw)


@pytest.mark.django_db
def test_scan_fires_plain_event_within_window(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=30)
    now = timezone.now()
    ev = _mk_event(user, personal, now + timedelta(minutes=20))  # глобальный порог 30 → в окне
    fired = scan_event_reminders()
    assert fired == 1
    ev.refresh_from_db()
    assert ev.reminder_sent is True
    assert Notification.objects.filter(user=user, type="planner.event_reminder").count() == 1


@pytest.mark.django_db
def test_scan_skips_event_outside_window(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=15)
    now = timezone.now()
    _mk_event(user, personal, now + timedelta(hours=2))  # далеко за порогом
    assert scan_event_reminders() == 0
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_scan_individual_zero_disables(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=60)
    now = timezone.now()
    ev = _mk_event(user, personal, now + timedelta(minutes=10), reminder_minutes_before=0)
    assert scan_event_reminders() == 0
    ev.refresh_from_db()
    assert ev.reminder_sent is False


@pytest.mark.django_db
def test_scan_dedup_after_fired(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=30)
    now = timezone.now()
    _mk_event(user, personal, now + timedelta(minutes=10))
    assert scan_event_reminders() == 1
    assert scan_event_reminders() == 0  # reminder_sent уже стоит
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_scan_uses_individual_threshold(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=5)
    now = timezone.now()
    _mk_event(user, personal, now + timedelta(minutes=50), reminder_minutes_before=90)
    assert scan_event_reminders() == 1  # индивидуальный 90 > глобального 5


@pytest.mark.django_db
def test_scan_recurring_fires_and_anchors(user, personal):
    UserSettings.objects.create(user=user, reminder_default_minutes=0)
    now = timezone.now()
    ev = _mk_event(
        user, personal, now + timedelta(minutes=10),
        reminder_minutes_before=20, recurrence_rule="daily",
    )
    assert scan_event_reminders() == 1
    ev.refresh_from_db()
    assert ev.last_reminder_at is not None
    # повтор не сбрасывает reminder_sent, якорь выставлен на экземпляр
    assert ev.reminder_sent is False
    # второй прогон в том же окне — не спамит (last_reminder_at >= occurrence)
    assert scan_event_reminders() == 0
    assert Notification.objects.filter(user=user, type="planner.event_reminder").count() == 1


@pytest.mark.django_db
def test_scan_recurring_fires_next_occurrence_after_window(user, personal):
    from datetime import datetime, timezone as dt_tz
    now = datetime(2026, 10, 1, 9, 0, tzinfo=dt_tz.utc)
    with freeze_time(now):
        UserSettings.objects.create(user=user, reminder_default_minutes=0)
        _mk_event(user, personal, now + timedelta(days=1, minutes=10),
                  reminder_minutes_before=20, recurrence_rule="daily")
        assert scan_event_reminders() == 0  # завтрашний экземпляр ещё не в окне
    with freeze_time(now + timedelta(days=1)):
        assert scan_event_reminders() == 1
        assert Notification.objects.filter(user=user, type="planner.event_reminder").count() == 1


def test_beat_schedule_wired():
    from django.conf import settings as dj
    names = {v["task"] for v in dj.CELERY_BEAT_SCHEDULE.values()}
    assert scan_event_reminders.name == "notifications.scan_event_reminders"
    assert scan_event_reminders.name in names
    assert "notifications.scan_vehicle_reminders" in names


# --- 5.4: scan_vehicle_reminders (ТЗ 4.2.8) -------------------------------

@pytest.fixture
def vehicle(user):
    return Vehicle.objects.create(user=user, brand_custom="Kia", model_custom="Rio", current_mileage=100000)


@pytest.mark.django_db
def test_scan_insurance_expiring_creates_note_and_event(user, vehicle):
    UserSettings.objects.create(user=user, insurance_reminder_days=30)
    today = timezone.localdate()
    ins = Insurance.objects.create(user=user, vehicle=vehicle, company="Согласие",
                                   policy_number="ХХХ123", end_date=today + timedelta(days=10))
    assert scan_vehicle_reminders() >= 1
    ins.refresh_from_db()
    assert ins.reminder_created is True
    assert Notification.objects.filter(user=user, type="insurance.expiring").count() == 1
    ev = Event.objects.get(user=user, event_type="reminder")
    assert ev.scope.code == "personal"
    assert timezone.localdate(ev.start_at) == ins.end_date
    # перескан — не дублирует (флаг)
    assert scan_vehicle_reminders() == 0
    assert Notification.objects.filter(user=user, type="insurance.expiring").count() == 1
    assert Event.objects.filter(user=user, event_type="reminder").count() == 1


@pytest.mark.django_db
def test_scan_insurance_outside_lead_silent(user, vehicle):
    UserSettings.objects.create(user=user, insurance_reminder_days=5)
    today = timezone.localdate()
    Insurance.objects.create(user=user, vehicle=vehicle, end_date=today + timedelta(days=20))
    assert scan_vehicle_reminders() == 0
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_scan_planned_by_date(user, vehicle):
    UserSettings.objects.create(user=user, plan_reminder_days=7)
    now = timezone.now()
    pe = PlannedEvent.objects.create(user=user, vehicle=vehicle, description="ТО-60",
                                     reminder_type="date", planned_date=now + timedelta(days=3))
    assert scan_vehicle_reminders() >= 1
    n = Notification.objects.get(user=user, type="vehicle.planned_due")
    assert str(n.entity_id) == str(pe.pk)
    # второй прогон в тот же день — дедуп
    assert scan_vehicle_reminders() == 0
    assert Notification.objects.filter(user=user, type="vehicle.planned_due").count() == 1


@pytest.mark.django_db
def test_scan_planned_by_mileage(user, vehicle):
    UserSettings.objects.create(user=user)
    PlannedEvent.objects.create(user=user, vehicle=vehicle, description="Замена масла",
                                reminder_type="mileage", reminder_mileage=100300)
    # пробег 100000 < 100300 — ещё рано
    assert scan_vehicle_reminders() == 0
    vehicle.current_mileage = 100300
    vehicle.save(update_fields=["current_mileage"])
    assert scan_vehicle_reminders() >= 1
    assert Notification.objects.filter(user=user, type="vehicle.planned_due").count() == 1
    # выполненное не напоминает
    Notification.objects.all().delete()
    pe = PlannedEvent.objects.get()
    pe.is_done = True
    pe.save(update_fields=["is_done", "updated_at"])
    assert scan_vehicle_reminders() == 0


@pytest.mark.django_db
def test_scan_fines_daily_digest(user, vehicle):
    Fine.objects.create(user=user, vehicle=vehicle, amount=500, status="unpaid")
    Fine.objects.create(user=user, vehicle=vehicle, amount=1000, status="unpaid")
    Fine.objects.create(user=user, vehicle=vehicle, amount=800, status="paid")
    assert scan_vehicle_reminders() >= 1
    n = Notification.objects.get(user=user, type="vehicle.fines_unpaid")
    assert "2" in n.title
    assert "1500" in n.message
    # повтор в тот же день — дедуп
    assert scan_vehicle_reminders() == 0
    assert Notification.objects.filter(user=user, type="vehicle.fines_unpaid").count() == 1


@pytest.mark.django_db
def test_scan_transport_tax_on_configured_date(user):
    from datetime import datetime, timezone as dt_tz
    UserSettings.objects.create(user=user, transport_tax_month=12, transport_tax_day=1)
    with freeze_time(datetime(2026, 12, 1, 9, 30, tzinfo=dt_tz.utc)):
        assert scan_vehicle_reminders() >= 1
        assert Notification.objects.filter(user=user, type="vehicle.transport_tax").count() == 1
    with freeze_time(datetime(2026, 12, 2, 9, 30, tzinfo=dt_tz.utc)):
        assert scan_vehicle_reminders() == 0


# --- 5.5: почтовый ящик в UI ----------------------------------------------

@pytest.mark.django_db
def test_inbox_lists_only_own(client, user):
    other = User.objects.create_user(email="other@test.ru", password="pass12345")
    notify(user, "a", "Своё", channels=())
    notify(other, "a", "Чужое", channels=())
    assert client.get(reverse("notifications:inbox")).status_code == 302  # не залогинен
    client.force_login(user)
    resp = client.get(reverse("notifications:inbox"))
    assert "Своё" in resp.content.decode()
    assert "Чужое" not in resp.content.decode()


@pytest.mark.django_db
def test_inbox_unread_filter(client, user):
    a = notify(user, "a", "НепрочитанноеУведомление", channels=())
    b = notify(user, "b", "ПрочитанноеУведомление", channels=())
    b.is_read = True
    b.save(update_fields=["is_read"])
    client.force_login(user)
    resp = client.get(reverse("notifications:inbox"), {"filter": "unread"})
    html = resp.content.decode()
    assert "НепрочитанноеУведомление" in html and "ПрочитанноеУведомление" not in html
    assert str(a.pk) in html  # id строки для HTMX-swap


@pytest.mark.django_db
def test_mark_read_htmx(client, user):
    n = notify(user, "a", "Т", channels=())
    client.force_login(user)
    resp = client.post(
        reverse("notifications:mark_read", args=[n.pk]),
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    n.refresh_from_db()
    assert n.is_read is True
    assert "Прочитано" not in resp.content.decode()  # кнопка исчезла в обновлённой строке


@pytest.mark.django_db
def test_mark_read_idor(client, user):
    other = User.objects.create_user(email="other2@test.ru", password="pass12345")
    n = notify(other, "a", "Чужое", channels=())
    client.force_login(user)
    assert client.post(reverse("notifications:mark_read", args=[n.pk])).status_code == 404
    n.refresh_from_db()
    assert n.is_read is False


@pytest.mark.django_db
def test_mark_all_read(client, user):
    notify(user, "a", "1", channels=())
    notify(user, "b", "2", channels=())
    client.force_login(user)
    client.post(reverse("notifications:mark_all_read"), headers={"hx-request": "true"})
    assert Notification.objects.filter(user=user, is_read=False).count() == 0


@pytest.mark.django_db
def test_sidebar_bell_counter(client, user):
    from apps.notifications.context_processors import unread_notifications
    notify(user, "a", "1", channels=())
    notify(user, "b", "2", channels=())
    client.force_login(user)
    resp = client.get(reverse("core:dashboard"))
    assert resp.context["unread_notifications_count"] == 2
    assert resp.wsgi_request.user.is_authenticated
    req = MagicMock(path="/", user=user)
    assert unread_notifications(req)["unread_notifications_count"] == 2
