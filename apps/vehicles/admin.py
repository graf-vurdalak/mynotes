from django.contrib import admin

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


class ServicePhotoInline(admin.TabularInline):
    model = ServicePhoto
    extra = 0


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        "brand",
        "model",
        "license_plate",
        "user",
        "current_mileage",
        "is_default",
        "is_deleted",
    ]
    list_filter = ["is_default", "is_deleted", "fuel_type"]
    # "vin" исключён из поиска: поле EncryptedCharField (7.6, ТЗ 8.5) —
    # icontains по случайному IV никогда не совпадёт с шифртекстом (фикс ревью №5)
    search_fields = [
        "brand__name",
        "model__name",
        "brand_custom",
        "model_custom",
        "license_plate",
        "user__email",
    ]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FuelEntry)
class FuelEntryAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "fuel_date",
        "odometer",
        "volume_liters",
        "price_per_liter",
        "total_cost",
        "is_deleted",
    ]
    list_filter = ["is_deleted", "full_tank"]
    search_fields = [
        "vehicle__license_plate",
        "user__email",
        "station_custom_name",
    ]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_system", "sort_order"]
    list_filter = ["is_system"]
    search_fields = ["name", "user__email"]


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["title", "vehicle", "category", "amount", "purchase_date", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["title", "vehicle__license_plate", "user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "service_station",
        "amount",
        "service_date",
        "planning_event",
        "is_deleted",
    ]
    list_filter = ["is_deleted"]
    search_fields = ["work_description", "service_station", "vehicle__license_plate"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [ServicePhotoInline]

    def planning_event(self, obj):
        return obj.planned_event_id

    planning_event.short_description = "План. событие"


@admin.register(Fine)
class FineAdmin(admin.ModelAdmin):
    list_display = ["vehicle", "decision_number", "amount", "status", "fine_date", "is_deleted"]
    list_filter = ["status", "is_deleted"]
    search_fields = ["decision_number", "article", "vehicle__license_plate"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Insurance)
class InsuranceAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "insurance_type",
        "company",
        "policy_number",
        "end_date",
        "is_deleted",
    ]
    list_filter = ["insurance_type", "is_deleted", "reminder_created"]
    search_fields = ["company", "policy_number", "vehicle__license_plate"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(PlannedEvent)
class PlannedEventAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "description",
        "planned_date",
        "reminder_type",
        "estimated_cost",
        "is_deleted",
    ]
    list_filter = ["reminder_type", "is_deleted"]
    search_fields = ["description", "location", "vehicle__license_plate"]
    readonly_fields = ["id", "created_at", "updated_at"]
