from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    anonymous_urls = [
        "/login/",
        "/signup/",
        "/logout/",
        "/accounts/signup/",
        "/accounts/verification-sent/",
        "/accounts/rate-limited/",
        "/accounts/logout/",
        "/accounts/verify-email/",
        "/accounts/password/",
        "/accounts/yandex/",
        "/2fa/",
        "/admin/",
        "/api/",
        "/static/",
        # /media/ исключён из публичных путей: файлы отдаёт authorized-прокси
        # apps.core.views.media_file с проверкой владельца (План MinIO).
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)

        for url in self.anonymous_urls:
            if request.path_info.startswith(url):
                return self.get_response(request)

        login_url = settings.LOGIN_URL
        if "?" in login_url:
            login_url += "&next=" + request.path_info
        else:
            login_url += "?next=" + request.path_info
        return redirect(login_url)
