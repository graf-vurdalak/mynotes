from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.home, name="home"),
    path("vehicle/", views.vehicle_report, name="vehicle"),
    path("planner/", views.planner_report, name="planner"),
    path("export/<slug:dataset>.xlsx", views.export_xlsx, name="export_xlsx"),
    path("export/<slug:dataset>.pdf", views.export_pdf, name="export_pdf"),
]
