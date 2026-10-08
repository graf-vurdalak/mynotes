from django.contrib import admin
from .models import User, UserSettings, AuthToken, AuthSessionLog, AuditLog


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "display_name", "is_active", "email_verified", "date_joined"]
    list_filter = ["is_active", "email_verified", "is_staff"]
    search_fields = ["email", "display_name"]
    readonly_fields = ["id", "date_joined", "last_login", "created_at", "updated_at"]


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ["user", "default_currency", "timezone", "language"]
    search_fields = ["user__email"]


@admin.register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_active", "created_at", "expires_at", "last_used_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "user__email"]
    readonly_fields = ["id", "token_hash", "created_at", "last_used_at", "last_used_ip"]


@admin.register(AuthSessionLog)
class AuthSessionLogAdmin(admin.ModelAdmin):
    list_display = ["user", "ip_address", "provider", "created_at"]
    list_filter = ["provider"]
    search_fields = ["user__email", "ip_address"]
    readonly_fields = ["id", "created_at"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "user", "entity_type", "entity_id", "ip_address"]
    list_filter = ["action"]
    search_fields = ["user__email", "action", "entity_id"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
