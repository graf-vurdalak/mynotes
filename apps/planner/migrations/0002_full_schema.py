import uuid

import django.contrib.postgres.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Полная схема Записной книжки по ТЗ 5.4.

    Каркас ``planner_event`` (Этап 2) пуст — пересоздаётся с полным набором
    полей; добавляются Scope/Project/Status/Comment/StatusHistory/EventAttachment.
    """

    dependencies = [
        ("planner", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Guard: каркасная таблица должна быть пуста — иначе миграция падает,
        # а не уничтожает данные (ТЗ 5.1 soft-delete, deploy safety).
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF to_regclass('planner_event') IS NOT NULL
                   AND (SELECT count(*) FROM planner_event) > 0 THEN
                    RAISE EXCEPTION 'planner_event не пуста — пересоздание запрещено';
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # FK vehicle_planned_event.planner_event_id -> planner_event мешает пересозданию
        # пустой каркасной таблицы; пересоздаём таблицу вместе с констрейнтом.
        # Таблица может ещё не существовать (чистая БД: planner мигрируется раньше vehicles).
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF to_regclass('vehicle_planned_event') IS NOT NULL THEN
                    ALTER TABLE vehicle_planned_event
                        DROP CONSTRAINT IF EXISTS vehicle_planned_event_planner_event_id_fkey;
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.DeleteModel(name="Event"),
        migrations.CreateModel(
            name="Scope",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("code", models.CharField(max_length=20, verbose_name="Код")),
                ("name", models.CharField(max_length=50)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(app_label)s_%(class)ss", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_scope", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("color", models.CharField(default="#3B82F6", max_length=7)),
                ("is_archived", models.BooleanField(default=False)),
                ("scope", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projects", to="planner.scope")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(app_label)s_%(class)ss", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_project", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Status",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("code", models.CharField(max_length=30)),
                ("name", models.CharField(max_length=50)),
                ("color", models.CharField(default="#94A3B8", max_length=7)),
                ("sort_order", models.IntegerField(default=0)),
                ("is_system", models.BooleanField(default=False)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(app_label)s_%(class)ss", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_status", "ordering": ["sort_order", "created_at"]},
        ),
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True)),
                ("event_type", models.CharField(choices=[("task", "Задача"), ("meeting", "Встреча"), ("reminder", "Напоминание"), ("milestone", "Веха")], default="task", max_length=20)),
                ("priority", models.CharField(choices=[("low", "Низкий"), ("normal", "Обычный"), ("high", "Высокий"), ("urgent", "Срочный")], default="normal", max_length=10)),
                ("start_at", models.DateTimeField(blank=True, null=True)),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("location", models.CharField(blank=True, max_length=255)),
                ("estimated_minutes", models.IntegerField(blank=True, null=True)),
                ("actual_minutes", models.IntegerField(blank=True, null=True)),
                ("tags", django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=50), blank=True, default=list, size=None)),
                ("recurrence_rule", models.CharField(blank=True, max_length=100)),
                ("recurrence_count", models.IntegerField(blank=True, null=True)),
                ("recurrence_end", models.DateTimeField(blank=True, null=True)),
                ("reminder_minutes_before", models.IntegerField(blank=True, null=True)),
                ("reminder_sent", models.BooleanField(default=False)),
                ("source", models.CharField(choices=[("web", "Веб"), ("telegram", "Telegram")], default="web", max_length=10)),
                ("parent_event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="instances", to="planner.event")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="planner.project")),
                ("scope", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="planner.scope")),
                ("status", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="planner.status")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(app_label)s_%(class)ss", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_event", "ordering": ["start_at", "created_at"]},
        ),
        migrations.CreateModel(
            name="Comment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("text", models.TextField()),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="planner_comments", to=settings.AUTH_USER_MODEL)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="planner.event")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="planner_comment_ownerships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_comment", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="EventAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("file", models.FileField(upload_to="planner/%Y/%m/")),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("mime_type", models.CharField(blank=True, max_length=100)),
                ("size_bytes", models.IntegerField(default=0)),
                ("comment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="planner.comment")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="planner.event")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="%(app_label)s_%(class)ss", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "planner_event_attachment", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="StatusHistory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("comment", models.TextField(blank=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="planner.event")),
                ("from_status", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="planner.status")),
                ("to_status", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="planner.status")),
            ],
            options={"db_table": "planner_status_history", "ordering": ["changed_at"]},
        ),
        migrations.AddConstraint(
            model_name="scope",
            constraint=models.UniqueConstraint(fields=("user", "code"), name="uniq_user_scope_code"),
        ),
        migrations.AddConstraint(
            model_name="status",
            constraint=models.UniqueConstraint(fields=("user", "code"), name="uniq_user_status_code"),
        ),
        migrations.AddIndex(
            model_name="project",
            index=models.Index(fields=["user", "scope", "is_deleted"], name="planner_proj_user_sc_del_idx"),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["user", "scope", "is_deleted"], name="planner_eve_user_sc_del_idx"),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["user", "status"], name="planner_eve_user_stat_idx"),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["start_at"], name="planner_eve_start_at_idx"),
        ),
        # Восстановление FK vehicle_planned_event -> planner_event на существующих БД
        # (на чистой БД его создаёт vehicles.0001; здесь — только если констрейнт потерян).
        # reverse_sql дропает его перед откатом таблицы — round-trip down/up сохраняет инвариант.
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF to_regclass('vehicle_planned_event') IS NOT NULL
                   AND NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'vehicle_planned_event_planner_event_id_fkey'
                   ) THEN
                    ALTER TABLE vehicle_planned_event
                        ADD CONSTRAINT vehicle_planned_event_planner_event_id_fkey
                        FOREIGN KEY (planner_event_id) REFERENCES planner_event (id)
                        DEFERRABLE INITIALLY DEFERRED;
                END IF;
            END $$;
            """,
            reverse_sql="""
            DO $$
            BEGIN
                IF to_regclass('vehicle_planned_event') IS NOT NULL THEN
                    ALTER TABLE vehicle_planned_event
                        DROP CONSTRAINT IF EXISTS vehicle_planned_event_planner_event_id_fkey;
                END IF;
            END $$;
            """,
        ),
    ]
