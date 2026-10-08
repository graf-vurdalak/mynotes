from django.contrib import admin

from .models import BotChatBinding, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["type", "title", "user", "is_read", "sent_via_email", "sent_via_telegram", "created_at"]
    list_filter = ["type", "is_read"]
    search_fields = ["title", "message", "user__email"]
    readonly_fields = ["id", "created_at"]


@admin.register(BotChatBinding)
class BotChatBindingAdmin(admin.ModelAdmin):
    list_display = ["user", "bot", "chat_id", "updated_at"]
    list_filter = ["bot"]
    search_fields = ["user__email", "chat_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
