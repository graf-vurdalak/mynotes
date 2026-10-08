from django.contrib import admin

from .models import Comment, Event, EventAttachment, Project, Scope, Status, StatusHistory


@admin.register(Scope)
class ScopeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "user", "created_at"]
    list_filter = ["code"]
    search_fields = ["user__email", "name"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["title", "scope", "user", "is_archived", "created_at"]
    list_filter = ["is_archived", "scope__code"]
    search_fields = ["title", "user__email"]


@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "user", "sort_order", "is_system"]
    list_filter = ["is_system"]
    search_fields = ["name", "user__email"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "scope", "project", "status", "priority", "start_at", "created_at"]
    list_filter = ["scope__code", "event_type", "priority"]
    search_fields = ["title", "description", "user__email"]


class EventAttachmentInline(admin.TabularInline):
    model = EventAttachment
    extra = 0


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["event", "author", "created_at"]
    search_fields = ["text", "event__title"]
    inlines = [EventAttachmentInline]


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["event", "from_status", "to_status", "changed_by", "changed_at"]
