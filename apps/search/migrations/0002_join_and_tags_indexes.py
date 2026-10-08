"""Индексы для веток поиска, которых не хватило в 0001 (фикс ревью №11/№15).

* GIN на массив ``planner_event.tags`` — ветка ``tags @> ARRAY[term]``;
* gin_trgm_ops на ``name`` маленьких справочников — join-ветки (station/category/
  brand/model name), чтобы ``__icontains`` по related-полю тоже читался индексом.
"""

from django.db import migrations

TRGM_JOIN_INDEXES = [
    ("vehicle_fuel_station", "name"),   # fuel.station__name
    ("ref_car_brand", "name"),          # vehicle.brand__name
    ("ref_car_model", "name"),          # vehicle.model__name
    ("vehicle_purchase_category", "name"),  # purchase.category__name
]


def _join_index_name(table, column):
    return f"trgmjoin_{table}_{column}"


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # GIN на массив тегов (array_ops) — для ветки tags__contains
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS gin_planner_event_tags "
            "ON planner_event USING gin (tags)"
        )
        for table, column in TRGM_JOIN_INDEXES:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {_join_index_name(table, column)} "
                f"ON {table} USING gin ({column} gin_trgm_ops)"
            )


def backward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS gin_planner_event_tags")
        for table, column in TRGM_JOIN_INDEXES:
            cursor.execute(f"DROP INDEX IF EXISTS {_join_index_name(table, column)}")


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0001_trgm_search_indexes"),
        ("vehicles", "0009_encrypt_vehicle_vin"),
        ("planner", "0004_event_last_reminder_at"),
        ("references", "0002_carbrand_created_by_carbrand_is_system_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
