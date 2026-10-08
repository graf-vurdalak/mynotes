from .models import Notification


def unread_notifications(request):
    """Счётчик непрочитанных для колокола в сайдбаре (ТЗ 5.5)."""
    if not request.user.is_authenticated:
        return {}
    return {
        "unread_notifications_count": Notification.objects.filter(
            user=request.user, is_read=False
        ).count(),
    }
