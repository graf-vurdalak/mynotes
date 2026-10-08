from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import Notification


def inbox(request):
    """Почтовый ящик уведомлений пользователя (ТЗ 5.5)."""
    only_unread = request.GET.get("filter") == "unread"
    qs = Notification.objects.filter(user=request.user)
    if only_unread:
        qs = qs.filter(is_read=False)
    return render(
        request,
        "notifications/inbox.html",
        {"notifications": qs, "only_unread": only_unread, "active_page": "notifications"},
    )


@require_POST
def mark_read(request, pk):
    """Отметить прочитанным (HTMX, swap строки). Только своя запись — чужая 404 (защита IDOR)."""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return render(request, "notifications/partials/_row.html", {"n": notification})


@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return render(request, "notifications/inbox.html", {
        "notifications": Notification.objects.filter(user=request.user),
        "only_unread": False,
        "active_page": "notifications",
    })
