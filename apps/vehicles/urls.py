from django.urls import path

from . import views

app_name = "vehicles"

urlpatterns = [
    path("", views.vehicle_list, name="list"),
    path("new/", views.vehicle_create, name="create"),
    path("models-api/", views.vehicle_models_api, name="models_api"),
    path("fuel/stations-api/", views.fuel_stations_api, name="fuel_stations_api"),
    path("<uuid:pk>/", views.vehicle_detail, name="detail"),
    path("<uuid:pk>/edit/", views.vehicle_update, name="update"),
    path("<uuid:pk>/delete/", views.vehicle_delete, name="delete"),
    path("<uuid:pk>/default/", views.vehicle_set_default, name="set_default"),
    path("<uuid:pk>/fuel/new/", views.fuel_create, name="fuel_create"),
    path("<uuid:pk>/fuel/<uuid:fuel_pk>/edit/", views.fuel_update, name="fuel_update"),
    path("<uuid:pk>/fuel/<uuid:fuel_pk>/delete/", views.fuel_delete, name="fuel_delete"),
    path("<uuid:pk>/purchase/new/", views.purchase_create, name="purchase_create"),
    path(
        "<uuid:pk>/purchase/<uuid:purchase_pk>/edit/",
        views.purchase_update,
        name="purchase_update",
    ),
    path(
        "<uuid:pk>/purchase/<uuid:purchase_pk>/delete/",
        views.purchase_delete,
        name="purchase_delete",
    ),
    path("<uuid:pk>/service/new/", views.service_create, name="service_create"),
    path(
        "<uuid:pk>/service/<uuid:service_pk>/edit/",
        views.service_update,
        name="service_update",
    ),
    path(
        "<uuid:pk>/service/<uuid:service_pk>/delete/",
        views.service_delete,
        name="service_delete",
    ),
    path("<uuid:pk>/fine/new/", views.fine_create, name="fine_create"),
    path(
        "<uuid:pk>/fine/<uuid:fine_pk>/edit/",
        views.fine_update,
        name="fine_update",
    ),
    path(
        "<uuid:pk>/fine/<uuid:fine_pk>/delete/",
        views.fine_delete,
        name="fine_delete",
    ),
    path(
        "<uuid:pk>/fine/<uuid:fine_pk>/status/",
        views.fine_status,
        name="fine_status",
    ),
    path("<uuid:pk>/insurance/new/", views.insurance_create, name="insurance_create"),
    path(
        "<uuid:pk>/insurance/<uuid:insurance_pk>/edit/",
        views.insurance_update,
        name="insurance_update",
    ),
    path(
        "<uuid:pk>/insurance/<uuid:insurance_pk>/delete/",
        views.insurance_delete,
        name="insurance_delete",
    ),
    path("<uuid:pk>/plan/new/", views.plan_create, name="plan_create"),
    path(
        "<uuid:pk>/plan/<uuid:plan_pk>/edit/",
        views.plan_update,
        name="plan_update",
    ),
    path(
        "<uuid:pk>/plan/<uuid:plan_pk>/delete/",
        views.plan_delete,
        name="plan_delete",
    ),
]
