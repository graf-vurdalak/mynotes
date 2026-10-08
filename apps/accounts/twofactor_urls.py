from django.urls import path

from . import views

app_name = "2fa"

urlpatterns = [
    path("verify/", views.otp_verify, name="verify"),
]
