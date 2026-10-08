from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.i18n import t
from apps.references.models import CarModel, FuelStation

from . import services
from .forms import (
    FineForm,
    FuelEntryForm,
    InsuranceForm,
    PlannedEventForm,
    PurchaseForm,
    ServiceForm,
    VehicleForm,
)
from .models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    PurchaseCategory,
    Service,
    Vehicle,
)


@login_required
def vehicle_list(request):
    vehicles = list(
        services.owned_queryset(Vehicle, request.user).select_related("brand", "model")
    )

    now = timezone.now().date()
    month_start = now.replace(day=1)
    deadline = now + timedelta(days=30)

    for v in vehicles:
        unpaid = v.fines.filter(is_deleted=False, status="unpaid").count()
        expiring = v.insurances.filter(
            is_deleted=False, end_date__isnull=False, end_date__lte=deadline,
            end_date__gte=now, renewed_by__isnull=True,
        ).count()
        expired = v.insurances.filter(
            is_deleted=False, end_date__isnull=False, end_date__lt=now, renewed_by__isnull=True,
        ).count()
        v.notice_count = unpaid + expiring + expired
        v.unpaid_fines = unpaid
        v.expiring_insurances = expiring
        v.expired_insurances = expired
        v.fuel_month = services.fuel_summary(v.pk, since=month_start)
        v.purchases_month = services.purchase_summary(v.pk, since=month_start)
        v.expenses_month = (v.fuel_month["total_cost"] or 0) + (v.purchases_month["total"] or 0)

    fuel_month = (
        FuelEntry.objects.filter(
            vehicle__user=request.user, is_deleted=False, fuel_date__gte=month_start
        ).aggregate(
            s=Coalesce(
                Sum("total_cost"), 0, output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )["s"]
    )
    purchases_month = (
        Purchase.objects.filter(
            vehicle__user=request.user,
            is_deleted=False,
            purchase_date__gte=month_start,
        ).aggregate(
            s=Coalesce(
                Sum("amount"), 0, output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )["s"]
    )
    unpaid_fines = (
        Fine.objects.filter(
            vehicle__user=request.user, is_deleted=False, status="unpaid"
        ).count()
    )
    expiring_insurances = Insurance.objects.filter(
        vehicle__user=request.user,
        is_deleted=False,
        end_date__isnull=False,
        end_date__lte=deadline,
        renewed_by__isnull=True,
    ).count()

    context = {
        "vehicles": vehicles,
        "vehicle_count": len(vehicles),
        "total_mileage": sum(v.current_mileage or 0 for v in vehicles),
        "expenses_month": fuel_month + purchases_month,
        "fuel_month": fuel_month,
        "unpaid_fines": unpaid_fines,
        "expiring_insurances": expiring_insurances,
    }
    return render(request, "vehicles/vehicle_list.html", context)


@login_required
def vehicle_detail(request, pk):
    vehicle = get_object_or_404(
        Vehicle.objects.select_related("brand", "model"),
        pk=pk,
        user=request.user,
        is_deleted=False,
    )
    tab_counts = {
        "fuel": vehicle.fuel_entries.filter(is_deleted=False).count(),
        "purchase": vehicle.purchases.filter(is_deleted=False).count(),
        "service": vehicle.services.filter(is_deleted=False).count(),
        "fines": vehicle.fines.filter(is_deleted=False).count(),
        "insurance": vehicle.insurances.filter(is_deleted=False).count(),
        "planned": vehicle.planned_events.filter(is_deleted=False).count(),
    }

    # --- Определяем активный таб из URL ---
    explicit_tab = request.GET.get("tab", "")
    valid_tabs = {"fuel", "purchase", "service", "fines", "insurance", "planned", "stats"}
    if explicit_tab in valid_tabs:
        active_tab = explicit_tab
    else:
        # Автоопределение по параметрам фильтра
        param_to_tab = {
            "station": "fuel",
            "purchase_cat": "purchase",
            "fine_status": "fines",
            "plan_filter": "planned",
        }
        detected = None
        for param, tab in param_to_tab.items():
            if request.GET.get(param):
                detected = tab
                break
        active_tab = detected or "fuel"

    # --- Заправки (таб) ---
    station_filter = request.GET.get("station", "")
    entries_qs = vehicle.fuel_entries.filter(is_deleted=False).select_related("station")
    if station_filter:
        entries_qs = entries_qs.filter(station__name__iexact=station_filter)
    fuel_entries = list(entries_qs)
    services.attach_consumption(fuel_entries)

    now = timezone.now().date()
    month_start = now.replace(day=1)
    month_summary = services.fuel_summary(vehicle.pk, since=month_start)
    all_summary = services.fuel_summary(vehicle.pk)
    history = services.consumption_history(vehicle.pk)

    station_options = FuelStation.objects.filter(
        Q(is_system=True) | Q(created_by=request.user)
    ).order_by("name")

    # --- Покупки (таб) ---
    purchase_cat = request.GET.get("purchase_cat", "")
    purchases_qs = vehicle.purchases.filter(is_deleted=False).select_related("category")
    if purchase_cat:
        purchases_qs = purchases_qs.filter(category_id=purchase_cat)
    purchases = list(purchases_qs)

    purchase_cat_options = PurchaseCategory.objects.filter(
        Q(user__isnull=True) | Q(user=request.user)
    )

    # --- Сервис (таб) ---
    services_list = list(
        vehicle.services.filter(is_deleted=False).prefetch_related("photos")
    )

    # --- Штрафы (таб) ---
    fine_status_filter = request.GET.get("fine_status", "")
    fines_qs = vehicle.fines.filter(is_deleted=False).select_related("purchase")
    if fine_status_filter:
        fines_qs = fines_qs.filter(status=fine_status_filter)
    fines = list(fines_qs)

    # --- Страховки (таб) ---
    insurances = list(
        vehicle.insurances.filter(is_deleted=False).select_related("renewed_by")
    )

    # --- План (таб) ---
    plan_filter = request.GET.get("plan_filter", "")
    plans_qs = vehicle.planned_events.filter(is_deleted=False)
    if plan_filter == "date":
        plans_qs = plans_qs.filter(reminder_type="date")
    elif plan_filter == "mileage":
        plans_qs = plans_qs.filter(reminder_type="mileage")
    elif plan_filter == "done":
        plans_qs = plans_qs.filter(is_done=True)
    plans = list(plans_qs)
    services.attach_plan_context(plans, vehicle.current_mileage)

    context = {
        "vehicle": vehicle,
        "active_tab": active_tab,
        "tab_counts": tab_counts,
        "fuel_entries": fuel_entries,
        "fuel_station_options": station_options,
        "fuel_station_filter": station_filter,
        "recent_fuel_stations": services.recent_fuel_stations(request.user),
        "fuel_month": month_summary,
        "fuel_all": all_summary,
        "fuel_history": history,
        "last_fuel_entry": fuel_entries[0] if fuel_entries else None,
        "purchases": purchases,
        "purchase_cat_options": purchase_cat_options,
        "purchase_cat_filter": purchase_cat,
        "purchase_month": services.purchase_summary(vehicle.pk, since=month_start),
        "purchase_all": services.purchase_summary(vehicle.pk),
        "service_records": services_list,
        "service_year": services.service_summary(vehicle.pk, year=now.year),
        "fines": fines,
        "fine_status_filter": fine_status_filter,
        "fine_all": services.fine_summary(vehicle.pk),
        "fine_year": services.fine_summary(vehicle.pk, year=now.year),
        "insurances": insurances,
        "insurance_summary": services.insurance_summary(vehicle.pk),
        "today": now,
        "insurance_deadline": now + timedelta(days=30),
        "plans": plans,
        "plan_filter": plan_filter,
        "plan_summary": services.planned_summary(
            vehicle.pk, vehicle.current_mileage
        ),
        "stats": services.stats_overview(vehicle.pk),
    }
    return render(request, "vehicles/vehicle_detail.html", context)


@login_required
def vehicle_create(request):
    form = VehicleForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.user = request.user
        if form.cleaned_data.get("is_default") or not services.owned_queryset(
            Vehicle, request.user
        ).exists():
            vehicle.is_default = True
        vehicle.save()
        messages.success(request, t("cln.msg_vehicle_added"))
        return redirect(reverse("vehicles:update", args=[vehicle.pk]))
    return render(request, "vehicles/vehicle_form.html", {"form": form, "is_new": True})


@login_required
def vehicle_update(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk, user=request.user, is_deleted=False)
    form = VehicleForm(
        request.POST or None, request.FILES or None, instance=vehicle
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_vehicle_updated"))
        return redirect(reverse("vehicles:update", args=[pk]))
    return render(
        request,
        "vehicles/vehicle_form.html",
        {"form": form, "vehicle": vehicle, "is_new": False},
    )


@login_required
def vehicle_delete(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk, user=request.user, is_deleted=False)
    if request.method == "POST":
        services.owned_queryset(Vehicle, request.user).filter(pk=pk).update(
            is_default=False
        )
        vehicle.delete()
        messages.success(request, t("cln.msg_vehicle_deleted"))
    return redirect(reverse("vehicles:list"))


@login_required
def vehicle_set_default(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk, user=request.user, is_deleted=False)
    if request.method == "POST":
        services.set_default_vehicle(request.user, vehicle)
        messages.success(request, t("cln.msg_vehicle_active"))
    return redirect(reverse("vehicles:list"))


@login_required
def vehicle_models_api(request):
    """JSON-список моделей для зависимого select (по выбранной марке)."""
    brand_id = request.GET.get("brand")
    qs = CarModel.objects.filter(Q(is_system=True) | Q(created_by=request.user))
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    data = [
        {"id": str(m.id), "name": m.name, "brand": str(m.brand_id)}
        for m in qs.order_by("name")
    ]
    return JsonResponse({"models": data})


def _get_vehicle(user, pk):
    return get_object_or_404(Vehicle, pk=pk, user=user, is_deleted=False)


VALID_TABS = {"fuel", "purchase", "service", "fines", "insurance", "planned", "stats"}


def _detail_url_with_tab(vehicle_pk, tab=""):
    base = reverse("vehicles:detail", args=[vehicle_pk])
    if tab in VALID_TABS:
        return f"{base}?tab={tab}"
    return base


@login_required
def fuel_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    initial = {
        "vehicle": vehicle,
        "fuel_date": timezone.now().date(),
        "odometer": services.get_latest_odometer(vehicle.pk) or vehicle.current_mileage or 0,
        "fuel_type": vehicle.fuel_type,
    }
    form = FuelEntryForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_fuel_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/fuel_form.html",
        {
            "form": form,
            "vehicle": vehicle,
            "is_new": True,
            "recent_stations": services.recent_fuel_stations(request.user),
            "previous": vehicle.fuel_entries.filter(is_deleted=False).first(),
            "last_fuel_entry": vehicle.fuel_entries.filter(is_deleted=False).first(),
            "tab": tab, "active_tab": tab},
    )


@login_required
def fuel_update(request, pk, fuel_pk):
    vehicle = _get_vehicle(request.user, pk)
    entry = get_object_or_404(
        FuelEntry, pk=fuel_pk, vehicle=vehicle, user=request.user, is_deleted=False
    )
    form = FuelEntryForm(
        request.POST or None,
        request.FILES or None,
        instance=entry,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_fuel_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/fuel_form.html",
        {
            "form": form,
            "vehicle": vehicle,
            "entry": entry,
            "is_new": False,
            "recent_stations": services.recent_fuel_stations(request.user),
            "previous": vehicle.fuel_entries.filter(is_deleted=False).first(),
            "last_fuel_entry": vehicle.fuel_entries.filter(is_deleted=False).first(),
            "tab": tab, "active_tab": tab},
    )


@login_required
def fuel_delete(request, pk, fuel_pk):
    vehicle = _get_vehicle(request.user, pk)
    entry = get_object_or_404(
        FuelEntry, pk=fuel_pk, vehicle=vehicle, user=request.user, is_deleted=False
    )
    if request.method == "POST":
        entry.delete()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_fuel_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def fuel_stations_api(request):
    """JSON-список АЗС для поиска (системные + пользовательские)."""
    q = request.GET.get("q", "").strip()
    qs = FuelStation.objects.filter(Q(is_system=True) | Q(created_by=request.user))
    if q:
        qs = qs.filter(name__icontains=q)
    data = [
        {
            "id": str(s.id),
            "name": s.name,
            "brand": s.brand,
            "address": s.address,
        }
        for s in qs[:10]
    ]
    return JsonResponse({"stations": data})


@login_required
def purchase_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    initial = {
        "vehicle": vehicle,
        "purchase_date": timezone.now().date(),
        "odometer": services.get_latest_odometer(vehicle.pk)
        or vehicle.current_mileage
        or 0,
    }
    form = PurchaseForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_purchase_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/purchase_form.html",
        {"form": form, "vehicle": vehicle, "is_new": True, "tab": tab, "active_tab": tab},
    )


@login_required
def purchase_update(request, pk, purchase_pk):
    vehicle = _get_vehicle(request.user, pk)
    purchase = get_object_or_404(
        Purchase,
        pk=purchase_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    form = PurchaseForm(
        request.POST or None,
        request.FILES or None,
        instance=purchase,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_purchase_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/purchase_form.html",
        {"form": form, "vehicle": vehicle, "purchase": purchase, "is_new": False, "tab": tab, "active_tab": tab},
    )


@login_required
def purchase_delete(request, pk, purchase_pk):
    vehicle = _get_vehicle(request.user, pk)
    purchase = get_object_or_404(
        Purchase,
        pk=purchase_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        purchase.delete()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_purchase_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def service_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    initial = {
        "vehicle": vehicle,
        "service_date": timezone.now().date(),
        "odometer": services.get_latest_odometer(vehicle.pk)
        or vehicle.current_mileage
        or 0,
    }
    form = ServiceForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_service_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/service_form.html",
        {"form": form, "vehicle": vehicle, "is_new": True, "tab": tab, "active_tab": tab},
    )


@login_required
def service_update(request, pk, service_pk):
    vehicle = _get_vehicle(request.user, pk)
    service = get_object_or_404(
        Service,
        pk=service_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    form = ServiceForm(
        request.POST or None,
        request.FILES or None,
        instance=service,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_service_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/service_form.html",
        {"form": form, "vehicle": vehicle, "service": service, "is_new": False, "tab": tab, "active_tab": tab},
    )


@login_required
def service_delete(request, pk, service_pk):
    vehicle = _get_vehicle(request.user, pk)
    service = get_object_or_404(
        Service,
        pk=service_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        service.delete()
        services.recalc_vehicle_mileage(vehicle)
        messages.success(request, t("cln.msg_service_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def fine_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    initial = {"vehicle": vehicle, "fine_date": timezone.now().date()}
    form = FineForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_fine_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/fine_form.html",
        {"form": form, "vehicle": vehicle, "is_new": True, "tab": tab, "active_tab": tab},
    )


@login_required
def fine_update(request, pk, fine_pk):
    vehicle = _get_vehicle(request.user, pk)
    fine = get_object_or_404(
        Fine,
        pk=fine_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    form = FineForm(
        request.POST or None,
        request.FILES or None,
        instance=fine,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_fine_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/fine_form.html",
        {"form": form, "vehicle": vehicle, "fine": fine, "is_new": False, "tab": tab, "active_tab": tab},
    )


@login_required
def fine_delete(request, pk, fine_pk):
    vehicle = _get_vehicle(request.user, pk)
    fine = get_object_or_404(
        Fine,
        pk=fine_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        fine.delete()
        messages.success(request, t("cln.msg_fine_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def insurance_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    form = InsuranceForm(
        request.POST or None,
        request.FILES or None,
        initial={"vehicle": vehicle},
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_insurance_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/insurance_form.html",
        {"form": form, "vehicle": vehicle, "is_new": True, "tab": tab, "active_tab": tab},
    )


@login_required
def insurance_update(request, pk, insurance_pk):
    vehicle = _get_vehicle(request.user, pk)
    insurance = get_object_or_404(
        Insurance,
        pk=insurance_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    form = InsuranceForm(
        request.POST or None,
        request.FILES or None,
        instance=insurance,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_insurance_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/insurance_form.html",
        {"form": form, "vehicle": vehicle, "insurance": insurance, "is_new": False, "tab": tab, "active_tab": tab},
    )


@login_required
def insurance_delete(request, pk, insurance_pk):
    vehicle = _get_vehicle(request.user, pk)
    insurance = get_object_or_404(
        Insurance,
        pk=insurance_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        insurance.delete()
        messages.success(request, t("cln.msg_insurance_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def fine_status(request, pk, fine_pk):
    """Быстрая смена статуса штрафа (оплачен/не оплачен/оспаривается)."""
    vehicle = _get_vehicle(request.user, pk)
    fine = get_object_or_404(
        Fine,
        pk=fine_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        status = request.POST.get("status", "")
        if status in dict(Fine.STATUSES):
            fine.status = status
            if status == "paid":
                fine.paid_at = (
                    request.POST.get("paid_at")
                    or fine.paid_at
                    or fine.fine_date
                    or timezone.now().date()
                )
            else:
                fine.paid_at = None
            fine.save(update_fields=["status", "paid_at", "updated_at"])
            services.sync_fine_purchase(
                fine, request.user, bool(fine.link_purchase)
            )
            messages.success(request, t("cln.msg_fine_status"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))


@login_required
def plan_create(request, pk):
    vehicle = _get_vehicle(request.user, pk)
    form = PlannedEventForm(
        request.POST or None,
        initial={
            "vehicle": vehicle,
            "planned_date": timezone.now(),
        },
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_plan_added"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", "")
    return render(
        request,
        "vehicles/plan_form.html",
        {"form": form, "vehicle": vehicle, "is_new": True, "tab": tab, "active_tab": tab},
    )


@login_required
def plan_update(request, pk, plan_pk):
    vehicle = _get_vehicle(request.user, pk)
    event = get_object_or_404(
        PlannedEvent,
        pk=plan_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    form = PlannedEventForm(
        request.POST or None,
        instance=event,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, t("cln.msg_plan_updated"))
        tab = request.POST.get("tab", "")
        return redirect(_detail_url_with_tab(vehicle.pk, tab))
    tab = request.GET.get("tab", request.POST.get("tab", ""))
    return render(
        request,
        "vehicles/plan_form.html",
        {"form": form, "vehicle": vehicle, "event": event, "is_new": False, "tab": tab, "active_tab": tab},
    )


@login_required
def plan_delete(request, pk, plan_pk):
    vehicle = _get_vehicle(request.user, pk)
    event = get_object_or_404(
        PlannedEvent,
        pk=plan_pk,
        vehicle=vehicle,
        user=request.user,
        is_deleted=False,
    )
    if request.method == "POST":
        event.delete()
        messages.success(request, t("cln.msg_plan_deleted"))
    tab = request.POST.get("tab", "")
    return redirect(_detail_url_with_tab(vehicle.pk, tab))
