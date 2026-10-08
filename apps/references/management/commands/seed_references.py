from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Загрузка предзаполненных справочников (АЗС, стартовые категории покупок)."

    def handle(self, *args, **options):
        call_command("loaddata", "fuel_stations")
        call_command("loaddata", "purchase_categories")
        self.stdout.write(
            self.style.SUCCESS("Справочники загружены: АЗС и категории покупок.")
        )
