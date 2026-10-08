import json

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.references.models import CarBrand, CarModel


class Command(BaseCommand):
    help = (
        "Импорт справочника марок/моделей из открытого каталога. "
        "Источник — локальный JSON-файл или URL. Ожидаемый формат: "
        '[{"brand": "LADA", "country": "RU", "models": '
        '[{"name": "Granta", "year_from": 2011, "body_type": "sedan"}]}]'
    )

    def add_arguments(self, parser):
        parser.add_argument("source", help="Путь к JSON-файлу или URL каталога")
        parser.add_argument(
            "--noop",
            action="store_true",
            help="Только показать, что будет импортировано, без записи",
        )

    def _load(self, source):
        if source.startswith("http://") or source.startswith("https://"):
            try:
                response = requests.get(source, timeout=30)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"Не удалось загрузить каталог по URL: {exc}")
        try:
            with open(source, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError as exc:
            raise CommandError(f"Не удалось прочитать файл {source}: {exc}")

    @transaction.atomic
    def handle(self, *args, **options):
        source = options["source"]
        noop = options["noop"]
        data = self._load(source)
        if not isinstance(data, list):
            raise CommandError("Каталог должен быть списком брендов")

        created_brands = updated_brands = 0
        created_models = updated_models = 0

        for item in data:
            brand_name = str(item.get("brand", "")).strip()
            if not brand_name:
                continue
            brand, was_created = CarBrand.objects.get_or_create(
                name=brand_name,
                defaults={
                    "country": str(item.get("country", "")).strip(),
                    "is_system": True,
                    "is_active": True,
                },
            )
            if was_created:
                created_brands += 1
            else:
                updated_brands += 1

            for m in item.get("models", []):
                model_name = str(m.get("name", "")).strip()
                if not model_name:
                    continue
                model, m_created = CarModel.objects.update_or_create(
                    brand=brand,
                    name=model_name,
                    defaults={
                        "year_from": m.get("year_from"),
                        "year_to": m.get("year_to"),
                        "body_type": str(m.get("body_type", "")).strip(),
                        "is_system": True,
                    },
                )
                if m_created:
                    created_models += 1
                else:
                    updated_models += 1

        if noop:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("Режим --noop: изменения откачены"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Импортировано: брендов создано {created_brands}, обновлено {updated_brands}; "
                f"моделей создано {created_models}, обновлено {updated_models}."
            )
        )
