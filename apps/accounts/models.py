from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils.translation import gettext_lazy as _
import uuid


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set."))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    yandex_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "auth_user"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email or ""

    @property
    def initials(self):
        if self.display_name:
            parts = self.display_name.split()
            return "".join(p[0] for p in parts[:2]).upper()
        if self.email:
            return self.email[0].upper()
        return "?"


class UserSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="settings"
    )
    default_currency = models.CharField(max_length=3, default="RUB")
    timezone = models.CharField(max_length=50, default="Europe/Moscow")
    language = models.CharField(max_length=5, default="ru")
    reminder_default_minutes = models.IntegerField(default=30)
    dark_theme = models.BooleanField(default=False)
    # Напоминания Бортжурнала (ТЗ 4.2.8) — настраиваемые параметры
    insurance_reminder_days = models.IntegerField(default=30)  # за сколько дней до конца полиса
    plan_reminder_days = models.IntegerField(default=7)  # за сколько дней до планового события
    transport_tax_month = models.IntegerField(default=12)  # месяц уплаты транспортного налога (1-12)
    transport_tax_day = models.IntegerField(default=1)  # день уплаты (1-31)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_settings"

    def __str__(self):
        return f"Settings for {self.user.email}"


class AuthToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bot_tokens")
    token_hash = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "auth_token"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class AuthSessionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="session_logs")
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    provider = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_session_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.created_at}"


class AuditLog(models.Model):
    """Журнал критичных действий (ТЗ 5.5, 8.5: входы, токены, пароль/email, 2FA)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    old = models.JSONField(null=True, blank=True)
    new = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} by {self.user_id} {self.created_at:%Y-%m-%d %H:%M}"
