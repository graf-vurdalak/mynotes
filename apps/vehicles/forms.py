from apps.core.i18n import t
import decimal
import json
import re

from django import forms
from django.db.models import Q
from django.utils import timezone
from PIL import Image

from apps.references.models import CarBrand, CarModel, FuelStation

from .models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    PurchaseCategory,
    Service,
    ServicePhoto,
    Vehicle,
)

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

FUEL_TYPE_CHOICES = [
    ("", t("vehicle.fuel_type_choice")),
    ("ai92", t("vehicle.fuel.ai92")),
    ("ai95", t("vehicle.fuel.ai95")),
    ("ai98", t("vehicle.fuel.ai98")),
    ("ai100", t("vehicle.fuel.ai100")),
    ("diesel", t("vehicle.fuel.dt")),
    ("gas", t("vehicle.fuel.gas")),
    ("electric", t("vehicle.fuel.electric")),
]


def field_css(field):
    base = (
        "w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm "
        "focus:ring-2 focus:ring-blue-500 focus:border-transparent"
    )
    css = field.widget.attrs.get("class", "")
    field.widget.attrs["class"] = (css + " " + base).strip()


class VehicleForm(forms.ModelForm):
    """Форма автомобиля с зависимым выбором марки/модели из справочника.

    Поддерживает как выбор из каталога (brand->CarBrand, model->CarModel),
    так и ввод собственной («своей») марки/модели (brand_custom/model_custom).
    """

    brand = forms.ModelChoiceField(
        queryset=CarBrand.objects.filter(is_active=True),
        required=False,
        empty_label=t("vehicle.pick_brand"),
        label=t("vehicle.brand"),
    )
    brand_custom = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": t("vehicle.brand_custom_ph")}),
        label=t("vehicle.brand_custom"),
    )
    model = forms.ModelChoiceField(
        queryset=CarModel.objects.all(),
        required=False,
        empty_label=t("vehicle.pick_model"),
        label=t("vehicle.model"),
    )
    model_custom = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": t("vehicle.model_custom_ph")}),
        label=t("vehicle.model_custom"),
    )

    class Meta:
        model = Vehicle
        fields = [
            "brand",
            "brand_custom",
            "model",
            "model_custom",
            "year",
            "vin",
            "license_plate",
            "fuel_type",
            "engine_volume",
            "power_hp",
            "transmission",
            "drive_type",
            "current_mileage",
            "photo",
            "is_default",
        ]
        labels = {
            "year": t("vehicle.year"),
            "fuel_type": t("vehicle.fuel_type_choice"),
            "engine_volume": t("vehicle.engine_volume"),
            "power_hp": t("vehicle.power"),
            "transmission": t("vehicle.transmission"),
            "drive_type": t("vehicle.drive"),
            "current_mileage": t("vehicle.current_mileage"),
            "photo": t("vehicle.photo"),
            "is_default": t("vehicle.make_default"),
        }
        widgets = {
            "vin": forms.TextInput(
                attrs={"maxlength": "17", "placeholder": t("vehicle.vin_ph")}
            ),
            "license_plate": forms.TextInput(
                attrs={"placeholder": t("vehicle.plate_ph")}
            ),
        }

    def clean_vin(self):
        vin = self.cleaned_data.get("vin", "") or ""
        vin = vin.replace(" ", "").upper()
        if vin:
            if len(vin) != 17:
                raise forms.ValidationError(t("vehicle.vin_len"))
            if not VIN_RE.fullmatch(vin):
                raise forms.ValidationError(
                    t("vehicle.vin_chars")
                )
        return vin

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = (
            "w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm "
            "focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        )
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " " + base).strip()

    def clean(self):
        cleaned = super().clean()
        brand = cleaned.get("brand")
        brand_custom = (cleaned.get("brand_custom") or "").strip()
        model = cleaned.get("model")
        model_custom = (cleaned.get("model_custom") or "").strip()

        if not brand and not brand_custom:
            self.add_error("brand", t("vehicle.brand_required"))

        if brand:
            cleaned["brand_custom"] = ""
        else:
            cleaned["brand"] = None

        if model:
            if brand and model.brand_id and model.brand_id != brand.id:
                self.add_error("model", t("vehicle.model_brand_mismatch"))
            else:
                cleaned["model_custom"] = ""
        else:
            cleaned["model"] = None
            if not model_custom and brand is None:
                pass  # модель необязательна

        return cleaned

    def save(self, commit=True):
        vehicle = super().save(commit=False)
        vehicle.brand = self.cleaned_data.get("brand") or None
        vehicle.brand_custom = self.cleaned_data.get("brand_custom") or ""
        vehicle.model = self.cleaned_data.get("model") or None
        vehicle.model_custom = self.cleaned_data.get("model_custom") or ""
        if commit:
            vehicle.save()
        return vehicle


class FuelEntryForm(forms.ModelForm):
    """Форма заправки (макет 05) с авторасчётом суммы и поиском АЗС.

    Поле ``vehicle`` ограничено автомобилями пользователя; АЗС выбирается из
    справочника (системные + пользовательские) либо вводится произвольно.
    """

    FUEL_CHOICES = [("", t("vehicle.fuel_type_choice"))] + [
        (c[0], c[1]) for c in FUEL_TYPE_CHOICES if c[0]
    ]

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    station = forms.ModelChoiceField(
        queryset=FuelStation.objects.none(),
        required=False,
        label=t("vehicle.station"),
        empty_label=t("vehicle.station_none"),
    )
    station_custom_name = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "type": "text",
                "placeholder": t("vehicle.station_ph"),
                "autocomplete": "off",
                "x-model": "stationQuery",
                "x-ref": "stationInput",
            }
        ),
        label=t("vehicle.station"),
    )
    fuel_type = forms.ChoiceField(choices=FUEL_CHOICES, required=False, label=t("vehicle.fuel_type_choice"))
    fuel_date = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date"}, format="%Y-%m-%d"
        ),
        label=t("vehicle.fuel_date"),
    )

    class Meta:
        model = FuelEntry
        fields = [
            "vehicle",
            "fuel_date",
            "station",
            "station_custom_name",
            "fuel_type",
            "odometer",
            "volume_liters",
            "price_per_liter",
            "full_tank",
            "latitude",
            "longitude",
            "notes",
            "receipt_photo",
        ]
        labels = {
            "odometer": t("vehicle.odometer_fuel"),
            "volume_liters": t("vehicle.volume"),
            "price_per_liter": t("vehicle.price_per_liter"),
            "full_tank": t("vehicle.full_tank"),
            "latitude": t("vehicle.latitude"),
            "longitude": t("vehicle.longitude"),
            "notes": t("vehicle.notes"),
            "receipt_photo": t("vehicle.receipt_photo"),
        }
        widgets = {
            "odometer": forms.NumberInput(
                attrs={"type": "number", "placeholder": t("vehicle.odometer_km_ph")}
            ),
            "volume_liters": forms.NumberInput(
                attrs={"type": "number", "step": "0.01", "placeholder": "40.00", "x-model": "liters"}
            ),
            "price_per_liter": forms.NumberInput(
                attrs={"type": "number", "step": "0.01", "placeholder": "63.00", "x-model": "price"}
            ),
            "full_tank": forms.CheckboxInput(
                attrs={"class": "w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": "3", "placeholder": t("vehicle.fuel_notes_ph")}
            ),
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "55.751244"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "37.618423"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
            station_qs = FuelStation.objects.filter(
                Q(is_system=True) | Q(created_by=user)
            ).order_by("name")
            self.fields["station"].queryset = station_qs
            # Добавляем опцию "Добавить новую" в конец списка
            self.fields["station"].choices = list(station_qs.values_list("id", "name")) + [("__new__", t("vehicle.add_station"))]
        for field in self.fields.values():
            field_css(field)
        self.fields["full_tank"].widget.attrs["class"] = (
            "w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
        )

    def clean_odometer(self):
        odometer = self.cleaned_data.get("odometer")
        if odometer is None:
            raise forms.ValidationError(t("vehicle.odometer_required"))
        if odometer < 0:
            raise forms.ValidationError(t("vehicle.odometer_neg"))
        return odometer

    def clean(self):
        cleaned = super().clean()
        volume = cleaned.get("volume_liters")
        price = cleaned.get("price_per_liter")
        if volume and volume < 0:
            self.add_error("volume_liters", t("vehicle.volume_neg"))
        if price and price < 0:
            self.add_error("price_per_liter", t("vehicle.price_neg"))

        station = cleaned.get("station")
        custom = (cleaned.get("station_custom_name") or "").strip()
        if station == "__new__":
            # Пользователь выбрал "Добавить новую" — требуем заполнить кастомное название
            if not custom:
                self.add_error("station_custom_name", t("vehicle.station_name_required"))
            cleaned["station"] = None  # Не сохраняем "__new__" как FK
        elif station:
            cleaned["station_custom_name"] = ""
        elif not custom:
            cleaned["station"] = None
        return cleaned

    def save(self, commit=True):
        from . import services

        entry = super().save(commit=False)
        entry.user = self.cleaned_data.get("vehicle").user
        services.recalc_fuel_entry_totals(entry, commit=False)
        services.resolve_fuel_station(entry, entry.user)
        if commit:
            entry.save()
        return entry


class PurchaseForm(forms.ModelForm):
    """Форма покупки (макет 10).

    Категория выбирается из справочника (системные + пользовательские);
    ``items`` — список товаров, вводится динамически и передаётся как JSON.
    """

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    category = forms.ModelChoiceField(
        queryset=PurchaseCategory.objects.none(),
        required=False,
        label=t("vehicle.category"),
        empty_label=t("vehicle.category_none"),
    )
    purchase_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.purchase_date"),
    )
    items_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        label=t("vehicle.items"),
    )

    class Meta:
        model = Purchase
        fields = [
            "vehicle",
            "purchase_date",
            "category",
            "title",
            "amount",
            "odometer",
            "items_json",
            "description",
            "photo",
        ]
        labels = {
            "title": t("vehicle.item_name"),
            "amount": t("vehicle.amount"),
            "odometer": t("vehicle.odometer"),
            "description": t("vehicle.item_comment"),
            "photo": t("vehicle.receipt_photo"),
        }
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": t("vehicle.purchase_title_ph")}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "type": "number",
                    "step": "0.01",
                    "placeholder": "0",
                    "x-model": "amount",
                }
            ),
            "odometer": forms.NumberInput(
                attrs={
                    "type": "number",
                    "placeholder": t("vehicle.odometer_km_ph"),
                    "x-model": "odometer",
                }
            ),
            "description": forms.Textarea(
                attrs={"rows": "2", "placeholder": t("vehicle.purchase_desc_ph")}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
            self.fields["category"].queryset = PurchaseCategory.objects.filter(
                Q(user__isnull=True) | Q(user=user)
            )
        if self.instance and self.instance.pk and self.instance.items:
            self.initial["items_json"] = json.dumps(
                self.instance.items, ensure_ascii=False
            )
        else:
            self.fields["items_json"].initial = "[]"
        for field in self.fields.values():
            field_css(field)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount < 0:
            raise forms.ValidationError(t("vehicle.amount_neg"))
        return amount or 0

    def clean_odometer(self):
        odometer = self.cleaned_data.get("odometer")
        if odometer is not None and odometer < 0:
            raise forms.ValidationError(t("vehicle.odometer_neg"))
        return odometer

    def clean_items_json(self):
        raw = self.cleaned_data.get("items_json") or "[]"
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            raise forms.ValidationError(t("vehicle.items_bad_json"))
        if not isinstance(items, list):
            raise forms.ValidationError(t("vehicle.items_not_list"))
        return [item for item in items if item]

    def save(self, commit=True):
        purchase = super().save(commit=False)
        purchase.user = self.cleaned_data.get("vehicle").user
        purchase.items = self.cleaned_data.get("items_json") or []
        if commit:
            purchase.save()
        return purchase


class MultiFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """Поле загрузки нескольких файлов.

    Возвращает список ``UploadedFile`` вместо одного файла.
    """

    widget = MultiFileInput

    def to_python(self, data):
        if data in self.empty_values:
            return []
        if isinstance(data, (list, tuple)):
            return list(data)
        return [data]

    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages["required"], code="required")


class ServiceForm(forms.ModelForm):
    """Форма записи сервиса (макет 11).

    СТО, работы, стоимость, пробег, заказ-наряд и до 10 фото
    (проверка размера и MIME).
    """

    ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ
    MAX_PHOTOS = 10

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    service_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.date"),
    )
    photos = MultiFileField(required=False, label=t("vehicle.photo_field"))

    class Meta:
        model = Service
        fields = [
            "vehicle",
            "service_date",
            "service_station",
            "work_description",
            "amount",
            "odometer",
            "order_document",
        ]
        labels = {
            "service_station": t("vehicle.station_short"),
            "work_description": t("vehicle.works"),
            "amount": t("vehicle.cost"),
            "odometer": t("vehicle.odometer"),
            "order_document": t("vehicle.order_doc"),
        }
        widgets = {
            "service_station": forms.TextInput(
                attrs={"placeholder": t("vehicle.station_name_ph")}
            ),
            "work_description": forms.Textarea(
                attrs={
                    "rows": "3",
                    "placeholder": t("vehicle.works_ph"),
                }
            ),
            "amount": forms.NumberInput(
                attrs={"type": "number", "step": "0.01", "placeholder": "0"}
            ),
            "odometer": forms.NumberInput(
                attrs={"type": "number", "placeholder": t("vehicle.odometer_km_ph")}
            ),
            "order_document": forms.TextInput(
                attrs={"placeholder": t("vehicle.order_no_ph")}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
        for field in self.fields.values():
            field_css(field)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount < 0:
            raise forms.ValidationError(t("vehicle.cost_neg"))
        return amount or 0

    def clean_odometer(self):
        odometer = self.cleaned_data.get("odometer")
        if odometer is not None and odometer < 0:
            raise forms.ValidationError(t("vehicle.odometer_neg"))
        return odometer

    def clean_photos(self):
        files = self.cleaned_data.get("photos") or []
        existing = (
            self.instance.photos.count()
            if self.instance and self.instance.pk
            else 0
        )
        if len(files) + existing > self.MAX_PHOTOS:
            raise forms.ValidationError(t("vehicle.too_many_photos"))
        for f in files:
            if f.size > self.MAX_FILE_SIZE:
                raise forms.ValidationError(t("vehicle.file_too_large", name=f.name))
            if self._detect_image_format(f) not in self.ALLOWED_FORMATS:
                raise forms.ValidationError(
                    t("vehicle.file_bad_format", name=f.name)
                )
        return files

    def _detect_image_format(self, f) -> str | None:
        """Возвращает фактический формат изображения (PIL) или None.

        Проверяется реальное содержимое файла, а не заголовок ``content_type``.
        """
        try:
            with Image.open(f) as img:
                fmt = img.format
                img.verify()
            f.seek(0)
            return fmt
        except Exception:
            return None

    def save(self, commit=True):
        service = super().save(commit=False)
        service.user = self.cleaned_data.get("vehicle").user
        if commit:
            service.save()
            self._save_photos(service)
        return service

    def _save_photos(self, service):
        files = self.cleaned_data.get("photos") or []
        start = service.photos.count()
        for idx, f in enumerate(files, start=1):
            ServicePhoto.objects.create(
                service=service, image=f, sort_order=start + idx
            )


class FineForm(forms.ModelForm):
    """Форма штрафа (макет 12).

    УИН, статья КоАП, описание, сумма, фото постановления, статус/дата оплаты
    и связь с записью в «Покупках» (категория «Штрафы») — по схеме 2.8.
    """

    ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    fine_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.fine_date"),
    )
    status = forms.ChoiceField(choices=Fine.STATUSES, label=t("vehicle.status"))
    paid_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.paid_date"),
    )
    link_purchase = forms.BooleanField(required=False, label=t("vehicle.link_purchase"))

    class Meta:
        model = Fine
        fields = [
            "vehicle",
            "fine_date",
            "decision_number",
            "article",
            "amount",
            "status",
            "paid_at",
            "description",
            "photo",
        ]
        labels = {
            "decision_number": t("vehicle.uin"),
            "article": t("vehicle.article"),
            "amount": t("vehicle.amount"),
            "description": t("vehicle.fine_desc_label"),
            "photo": t("vehicle.fine_photo"),
        }
        widgets = {
            "decision_number": forms.TextInput(
                attrs={"maxlength": "25", "placeholder": t("vehicle.uin_ph")}
            ),
            "article": forms.TextInput(attrs={"placeholder": t("vehicle.article_ph")}),
            "amount": forms.NumberInput(
                attrs={"type": "number", "step": "0.01", "placeholder": "0"}
            ),
            "description": forms.Textarea(
                attrs={"rows": "3", "placeholder": t("vehicle.fine_desc_ph")}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
        if self.instance and self.instance.pk:
            self.initial["link_purchase"] = self.instance.link_purchase
        for field in self.fields.values():
            field_css(field)

    def clean_decision_number(self):
        value = (self.cleaned_data.get("decision_number") or "").strip()
        if value and (not value.isdigit() or not (20 <= len(value) <= 25)):
            raise forms.ValidationError(t("vehicle.uin_len"))
        return value

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount < 0:
            raise forms.ValidationError(t("vehicle.amount_neg"))
        return amount or 0

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return photo
        if photo.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError(t("vehicle.file_big"))
        if self._detect_image_format(photo) not in self.ALLOWED_FORMATS:
            raise forms.ValidationError(
                t("vehicle.bad_format")
            )
        return photo

    def _detect_image_format(self, f) -> str | None:
        try:
            with Image.open(f) as img:
                fmt = img.format
                img.verify()
            f.seek(0)
            return fmt
        except Exception:
            return None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == "paid" and not cleaned.get("paid_at"):
            cleaned["paid_at"] = cleaned.get("fine_date") or timezone.now().date()
        return cleaned

    def save(self, commit=True):
        from . import services

        fine = super().save(commit=False)
        fine.user = self.cleaned_data.get("vehicle").user
        if commit:
            fine.save()
            services.sync_fine_purchase(
                fine, fine.user, self.cleaned_data.get("link_purchase", False)
            )
        return fine


class InsuranceForm(forms.ModelForm):
    """Форма страховки (макет 13).

    Тип (ОСАГО/КАСКО/ДСАГО/Зелёная карта), компания, номер полиса, период
    действия, стоимость, фото полиса и задел напоминания ``reminder_created``.
    """

    ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.ins_start"),
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        label=t("vehicle.ins_end"),
    )
    reminder_created = forms.BooleanField(required=False, label=t("vehicle.remind_30"))
    renewed_by = forms.ModelChoiceField(
        queryset=Insurance.objects.none(),
        required=False,
        label=t("vehicle.renewed_by"),
        empty_label=t("vehicle.renewed_none"),
    )

    class Meta:
        model = Insurance
        fields = [
            "vehicle",
            "insurance_type",
            "company",
            "policy_number",
            "start_date",
            "end_date",
            "cost",
            "photo",
            "renewed_by",
        ]
        labels = {
            "insurance_type": t("vehicle.ins_type"),
            "company": t("vehicle.company"),
            "policy_number": t("vehicle.policy_number"),
            "cost": t("vehicle.cost"),
            "photo": t("vehicle.ins_photo"),
            "renewed_by": t("vehicle.renewed_by"),
        }
        widgets = {
            "company": forms.TextInput(
                attrs={"placeholder": t("vehicle.company_ph")}
            ),
            "policy_number": forms.TextInput(
                attrs={"placeholder": "XXX 0000000000"}
            ),
            "cost": forms.NumberInput(
                attrs={"type": "number", "step": "0.01", "placeholder": "0"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
        if self.instance and self.instance.pk and self.instance.vehicle_id:
            self.initial["reminder_created"] = self.instance.reminder_created
            vehicle = self.instance.vehicle
            self.fields["renewed_by"].queryset = Insurance.objects.filter(
                vehicle=vehicle, is_deleted=False
            ).exclude(pk=self.instance.pk)
        for field in self.fields.values():
            field_css(field)

    def clean_cost(self):
        cost = self.cleaned_data.get("cost")
        if cost is not None and cost < 0:
            raise forms.ValidationError(t("vehicle.cost_neg"))
        return cost or 0

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo:
            return photo
        if photo.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError(t("vehicle.file_big"))
        if self._detect_image_format(photo) not in self.ALLOWED_FORMATS:
            raise forms.ValidationError(
                t("vehicle.bad_format")
            )
        return photo

    def _detect_image_format(self, f) -> str | None:
        try:
            with Image.open(f) as img:
                fmt = img.format
                img.verify()
            f.seek(0)
            return fmt
        except Exception:
            return None

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", t("vehicle.ins_end_early"))
        return cleaned

    def save(self, commit=True):
        insurance = super().save(commit=False)
        insurance.user = self.cleaned_data.get("vehicle").user
        insurance.reminder_created = self.cleaned_data.get(
            "reminder_created", False
        )
        if commit:
            insurance.save()
        return insurance


class PlannedEventForm(forms.ModelForm):
    """Форма планового события (макет 14).

    Описание, дата/время, место, предполагаемая стоимость, тип напоминания
    (по дате / по пробегу) и целевой пробег. Тип выбирается переключателем —
    по дате и по пробегу (как на макете).
    """

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=t("vehicle.vehicle"),
        empty_label=t("vehicle.pick_vehicle"),
    )
    reminder_type = forms.ChoiceField(
        choices=[("date", t("vehicle.remind_date")), ("mileage", t("vehicle.remind_mileage"))],
        widget=forms.RadioSelect,
        initial="date",
        label=t("vehicle.reminder_type"),
    )
    planned_date = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        label=t("vehicle.datetime"),
    )
    estimated_cost = forms.CharField(
        required=False,
        widget=forms.NumberInput(
            attrs={
                "type": "number",
                "step": "0.01",
                "placeholder": "0",
                "x-model": "cost",
            }
        ),
        label=t("vehicle.estimated_cost"),
    )

    class Meta:
        model = PlannedEvent
        fields = [
            "vehicle",
            "description",
            "planned_date",
            "location",
            "estimated_cost",
            "reminder_type",
            "reminder_mileage",
            "is_done",
        ]
        labels = {
            "description": t("vehicle.description"),
            "location": t("vehicle.place"),
            "reminder_mileage": t("vehicle.odometer"),
            "is_done": t("vehicle.done"),
        }
        widgets = {
            "description": forms.TextInput(
                attrs={"placeholder": t("vehicle.planned_desc_ph")}
            ),
            "location": forms.TextInput(attrs={"placeholder": t("vehicle.planned_place_ph")}),
            "reminder_mileage": forms.NumberInput(
                attrs={"type": "number", "placeholder": t("vehicle.odometer_km_ph")}
            ),
            "is_done": forms.CheckboxInput(
                attrs={
                    "class": "w-5 h-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                user=user, is_deleted=False
            )
        for field in self.fields.values():
            if field.widget.__class__.__name__ == "RadioSelect":
                continue
            field_css(field)

    def clean_description(self):
        description = (self.cleaned_data.get("description") or "").strip()
        if not description:
            raise forms.ValidationError(t("vehicle.planned_desc_required"))
        return description

    def clean_estimated_cost(self):
        raw = (self.cleaned_data.get("estimated_cost") or "").strip()
        if not raw:
            return None
        value = self._normalize_number(raw)
        try:
            cost = decimal.Decimal(value)
        except (decimal.InvalidOperation, ValueError):
            raise forms.ValidationError(t("vehicle.cost_parse"))
        if cost < 0:
            raise forms.ValidationError(t("vehicle.cost_neg"))
        return cost

    @staticmethod
    def _normalize_number(raw):
        return (
            str(raw)
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(" ₽", "")
            .replace("₽", "")
            .replace(",", ".")
        )

    def clean(self):
        cleaned = super().clean()
        rtype = cleaned.get("reminder_type")
        mileage = cleaned.get("reminder_mileage")
        if rtype == "mileage" and mileage is None:
            self.add_error(
                "reminder_mileage",
                t("vehicle.target_mileage_required"),
            )
        elif mileage is not None and mileage < 0:
            self.add_error("reminder_mileage", t("vehicle.odometer_neg"))
        return cleaned

    def save(self, commit=True):
        event = super().save(commit=False)
        event.user = self.cleaned_data.get("vehicle").user
        if commit:
            event.save()
        return event


