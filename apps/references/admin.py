from django.contrib import admin

from .models import CarBrand, CarModel, FuelStation


@admin.register(CarBrand)
class CarBrandAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "is_system", "is_active", "created_by"]
    list_filter = ["is_system", "is_active"]
    search_fields = ["name", "country"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(CarModel)
class CarModelAdmin(admin.ModelAdmin):
    list_display = ["brand", "name", "year_from", "year_to", "body_type", "is_system"]
    list_filter = ["is_system"]
    search_fields = ["name", "brand__name"]
    autocomplete_fields = ["brand"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ["name", "brand", "is_system", "address"]
    list_filter = ["is_system"]
    search_fields = ["name", "brand", "address"]
