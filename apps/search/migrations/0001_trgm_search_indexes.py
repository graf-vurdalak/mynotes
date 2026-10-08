"""GIN-индексы pg_trgm для глобального поиска (ТЗ 4.4, Этап 7.7).

Индексы на чужих таблицах живут здесь осознанно: поиск — фича apps/search, и
владеет она и своими индексами. ILIKE/`%similarity%` ускоряются gin_trgm_ops.
tsvector-выражения строятся на лету в запросах (объёмы персональные —
отдельный выражения-индекс не заводим, см. docs/progress.md 7.7).

Ревью №14: atomic=False + CREATE INDEX CONCURRENTLY (не блокирует запись),
проверка indisvalid с одной пересборкой — упавший CONCURRENTLY build оставляет
INVALID-индекс.
"""

from django.contrib.postgres.operations import CreateExtension
from django.db import migrations

TRGM_INDEXES = [
    ("vehicle_vehicle", "brand_custom"),
    ("vehicle_vehicle", "model_custom"),
    ("vehicle_vehicle", "license_plate"),
    ("vehicle_vehicle", "notes"),
    ("vehicle_fuel_entry", "station_custom_name"),
    ("vehicle_fuel_entry", "notes"),
    ("vehicle_purchase", "title"),
    ("vehicle_purchase", "description"),
    ("vehicle_service", "service_station"),
    ("vehicle_service", "work_description"),
    ("vehicle_fine", "decision_number"),
    ("vehicle_fine", "article"),
    ("vehicle_fine", "description"),
    ("vehicle_insurance", "company"),
    ("vehicle_insurance", "policy_number"),
    ("vehicle_planned_event", "description"),
    ("vehicle_planned_event", "location"),
    ("planner_event", "title"),
    ("planner_event", "description"),
    ("planner_event", "location"),
    ("planner_project", "title"),
    ("planner_project", "description"),
]


def _index_name(table, column):
    return f"trgm_{table}_{column}"


def _is_valid(cursor, name):
    cursor.execute(
        "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = %s AND NOT i.indisvalid",
        [name],
    )
    return cursor.fetchone() is not None


def _create_trgm(cursor, table, column):
    name = _index_name(table, column)
    cursor.execute(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
        f"ON {table} USING gin ({column} gin_trgm_ops)"
    )
    if _is_valid(cursor, name):
        # неудачный CONCURRENTLY build — пересобрать один раз
        cursor.execute(f"DROP INDEX IF EXISTS {name}")
        cursor.execute(
            f"CREATE INDEX CONCURRENTLY {name} ON {table} USING gin ({column} gin_trgm_ops)"
        )
        if _is_valid(cursor, name):
            raise RuntimeError(f"GIN-индекс {name} не удалось построить (INVALID)")


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table, column in TRGM_INDEXES:
            _create_trgm(cursor, table, column)


def backward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table, column in TRGM_INDEXES:
            cursor.execute(f"DROP INDEX IF EXISTS {_index_name(table, column)}")


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("vehicles", "0009_encrypt_vehicle_vin"),
        ("planner", "0004_event_last_reminder_at"),
    ]

    operations = [
        CreateExtension("pg_trgm"),
        migrations.RunPython(forward, backward),
    ]
