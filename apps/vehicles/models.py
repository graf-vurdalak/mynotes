import os
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.fields import EncryptedCharField


class OwnedModel(models.Model):
    """Абстрактная база для сущностей Бортжурнала.

    UUID PK, привязка к пользователю, soft-delete и отметки времени — по схеме ТЗ 5.3.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.save(update_fields=["is_deleted", "updated_at"])

    def hard_delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)


class Vehicle(OwnedModel):
    FUEL_TYPES = [
        ("petrol", _("Бензин")),
        ("diesel", _("Дизель")),
        ("electric", _("Электро")),
        ("hybrid", _("Гибрид")),
        ("gas", _("Газ")),
    ]
    TRANSMISSIONS = [
        ("mt", _("МКПП")),
        ("at", _("АКПП")),
        ("cvt", _("Вариатор")),
        ("robot", _("Робот")),
    ]
    DRIVE_TYPES = [
        ("fwd", _("Передний")),
        ("rwd", _("Задний")),
        ("awd", _("Полный")),
    ]

    brand = models.ForeignKey(
        "references.CarBrand",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    model = models.ForeignKey(
        "references.CarModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    brand_custom = models.CharField(max_length=100, blank=True)
    model_custom = models.CharField(max_length=100, blank=True)
    year = models.SmallIntegerField(null=True, blank=True)
    vin = EncryptedCharField(max_length=255, blank=True)
    license_plate = models.CharField(max_length=20, blank=True)
    fuel_type = models.CharField(max_length=20, choices=FUEL_TYPES, blank=True)
    engine_volume = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    power_hp = models.IntegerField(null=True, blank=True)
    transmission = models.CharField(
        max_length=20, choices=TRANSMISSIONS, blank=True
    )
    drive_type = models.CharField(
        max_length=10, choices=DRIVE_TYPES, blank=True
    )
    color = models.CharField(max_length=50, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    purchase_currency = models.CharField(max_length=3, default="RUB")
    current_mileage = models.IntegerField(null=True, blank=True, default=0)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    photo = models.ImageField(upload_to="vehicles/", blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "vehicle_vehicle"
        ordering = ["-created_at"]

    def __str__(self):
        brand = self.brand_custom or (self.brand.name if self.brand else "")
        model = self.model_custom or (self.model.name if self.model else "")
        return f"{brand} {model}".strip() or str(self.id)


class FuelEntry(OwnedModel):
    station = models.ForeignKey(
        "references.FuelStation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fuel_entries",
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="fuel_entries"
    )
    station_custom_name = models.CharField(max_length=200, blank=True)
    fuel_date = models.DateField()
    odometer = models.IntegerField()
    fuel_type = models.CharField(max_length=20, blank=True)
    volume_liters = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    price_per_liter = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="RUB")
    full_tank = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    notes = models.TextField(blank=True)
    receipt_photo = models.ImageField(upload_to="vehicles/fuel/", blank=True)
    source = models.CharField(
        max_length=10,
        choices=[("web", _("Веб")), ("telegram", _("Telegram"))],
        default="web",
    )

    class Meta:
        db_table = "vehicle_fuel_entry"
        ordering = ["-fuel_date", "-created_at"]

    def __str__(self):
        return f"{self.fuel_date} / {self.vehicle_id}"


class PurchaseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="purchase_categories",
    )
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=7, blank=True)
    sort_order = models.IntegerField(default=0)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vehicle_purchase_category"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Purchase(OwnedModel):
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="purchases"
    )
    category = models.ForeignKey(
        PurchaseCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="RUB")
    purchase_date = models.DateField(null=True, blank=True)
    odometer = models.IntegerField(null=True, blank=True)
    items = models.JSONField(default=list, blank=True)
    photo = models.ImageField(upload_to="vehicles/purchases/", blank=True)
    source = models.CharField(
        max_length=10,
        choices=[("web", _("Веб")), ("telegram", _("Telegram"))],
        default="web",
    )

    class Meta:
        db_table = "vehicle_purchase"
        ordering = ["-purchase_date", "-created_at"]

    def __str__(self):
        return self.title


class PlannedEvent(OwnedModel):
    REMINDER_TYPES = [
        ("mileage", _("По пробегу")),
        ("date", _("По дате")),
        ("both", _("Оба")),
    ]

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="planned_events"
    )
    planner_event = models.ForeignKey(
        "planner.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicle_events",
    )
    description = models.TextField(blank=True)
    planned_date = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    estimated_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency_code = models.CharField(max_length=3, default="RUB")
    reminder_type = models.CharField(
        max_length=20, choices=REMINDER_TYPES, default="date"
    )
    reminder_mileage = models.IntegerField(null=True, blank=True)
    is_done = models.BooleanField(default=False)

    class Meta:
        db_table = "vehicle_planned_event"
        ordering = ["-planned_date", "-created_at"]

    def __str__(self):
        return self.description or str(self.id)


class Service(OwnedModel):
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="services"
    )
    service_station = models.CharField(max_length=255, blank=True)
    work_description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="RUB")
    service_date = models.DateField(null=True, blank=True)
    odometer = models.IntegerField(null=True, blank=True)
    order_document = models.TextField(blank=True)
    planned_event = models.ForeignKey(
        PlannedEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
    )
    source = models.CharField(
        max_length=10,
        choices=[("web", _("Веб")), ("telegram", _("Telegram"))],
        default="web",
    )

    class Meta:
        db_table = "vehicle_service"
        ordering = ["-service_date", "-created_at"]

    def __str__(self):
        return self.work_description or str(self.id)


def service_photo_path(instance, filename):
    """Имя файла фото — UUID сервиса + порядковый номер файла.

    Гарантирует, что файлы из разных объектов не получат одинаковые имена.
    """
    ext = os.path.splitext(filename)[1].lower()
    return f"vehicles/service/{instance.service_id}_{instance.sort_order}{ext}"


class ServicePhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to=service_photo_path)
    sort_order = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vehicle_service_photo"
        ordering = ["sort_order", "uploaded_at"]

    def __str__(self):
        return f"Фото {self.image.name}"


class Fine(OwnedModel):
    STATUSES = [
        ("unpaid", _("Не оплачен")),
        ("paid", _("Оплачен")),
        ("disputed", _("Оспаривается")),
    ]

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="fines"
    )
    fine_date = models.DateField(null=True, blank=True)
    decision_number = models.CharField(max_length=50, blank=True)
    article = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="RUB")
    status = models.CharField(max_length=20, choices=STATUSES, default="unpaid")
    paid_at = models.DateField(null=True, blank=True)
    link_purchase = models.BooleanField(
        default=False,
        help_text="Показывать штраф в расходах (запись в покупках с категорией «Штрафы»)",
    )
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fines",
    )
    photo = models.ImageField(upload_to="vehicles/fines/", blank=True)
    source = models.CharField(
        max_length=10,
        choices=[("web", _("Веб")), ("telegram", _("Telegram"))],
        default="web",
    )

    class Meta:
        db_table = "vehicle_fine"
        ordering = ["-fine_date", "-created_at"]

    def __str__(self):
        return self.decision_number or str(self.id)


class Insurance(OwnedModel):
    INSURANCE_TYPES = [
        ("osago", _("ОСАГО")),
        ("kasko", _("КАСКО")),
        ("dsago", _("ДСАГО")),
        ("greencard", _("Зелёная карта")),
    ]

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="insurances"
    )
    insurance_type = models.CharField(
        max_length=20, choices=INSURANCE_TYPES, default="osago"
    )
    company = models.CharField(max_length=200, blank=True)
    policy_number = models.CharField(max_length=50, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="RUB")
    photo = models.ImageField(upload_to="vehicles/insurances/", blank=True)
    reminder_created = models.BooleanField(default=False)
    renewed_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="renewed_policies",
        verbose_name=_("Продлён полисом"),
    )

    class Meta:
        db_table = "vehicle_insurance"
        ordering = ["-start_date", "-created_at"]

    def __str__(self):
        return f"{self.get_insurance_type_display()} {self.policy_number}"

    @property
    def is_renewed(self) -> bool:
        return self.renewed_by is not None
