"""Перешифровка существующих VIN в Fernet (ТЗ 8.5, этап 7.6; ревью №4/№14).

Ревью №4: guard — в не-DEBUG refuse выставлять ключ от SECRET_KEY, иначе
необратимое шифрование «чужим» ключем (ротация SECRET_KEY делает VIN нечитаемыми:
from_db_value отдаёт шифр как legacy, форма невалидна, reverse цепочки падает).

Ревью №14: atomic=False + параметризованный executemany чанками (не N save()
в одном длинном транзакте).
"""

from django.db import migrations

from apps.core.crypto import encrypt_value

CHUNK = 500


def _require_key():
    from django.conf import settings

    if not (getattr(settings, "FERNET_KEY", "") or "").strip() and not settings.DEBUG:
        raise RuntimeError(
            "vehicles.0009: FERNET_KEY не задан — VIN будут шифроваться производным от "
            "SECRET_KEY, и их чтение сломается при первой ротации SECRET_KEY. "
            "Задайте FERNET_KEY в env/образе до применения миграции."
        )


def _flush(schema_editor, pairs):
    with schema_editor.connection.cursor() as cursor:
        cursor.executemany(
            "UPDATE vehicle_vehicle SET vin = %s WHERE id = %s",
            pairs,
        )


def encrypt_existing_vins(apps, schema_editor):
    Vehicle = apps.get_model("vehicles", "Vehicle")
    rows = Vehicle.objects.exclude(vin="")
    if rows.exists():
        # Guard осмысленен только при backfill существующих VIN; на пустой БД
        # (тесты, свежий dev) не блокируем миграцию — за ключ отвечает
        # core.E001 (manage.py check).
        _require_key()
    # vehicle.vin расшифрован from_db_value (или legacy-plaintext как есть);
    # пишем шифртекст напрямую, повторный запуск идемпотентен (перешифровка).
    pairs = []
    for vehicle in rows.iterator(chunk_size=CHUNK):
        pairs.append((encrypt_value(vehicle.vin), vehicle.pk))
        if len(pairs) >= CHUNK:
            _flush(schema_editor, pairs)
            pairs = []
    if pairs:
        _flush(schema_editor, pairs)


def decrypt_existing_vins(apps, schema_editor):
    Vehicle = apps.get_model("vehicles", "Vehicle")
    pairs = []
    for vehicle in Vehicle.objects.exclude(vin="").iterator(chunk_size=CHUNK):
        # На момент reverse поле ещё EncryptedCharField: vehicle.vin уже plaintext
        # (from_db_value). Пишем через cursor, обходя get_db_prep_value.
        pairs.append((vehicle.vin, vehicle.pk))
        if len(pairs) >= CHUNK:
            _flush(schema_editor, pairs)
            pairs = []
    if pairs:
        _flush(schema_editor, pairs)


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("vehicles", "0008_alter_vehicle_vin"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_vins, decrypt_existing_vins),
    ]
