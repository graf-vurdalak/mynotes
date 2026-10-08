from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts.tokens import verify_token


def client_ip(request) -> str | None:
    """IP клиента с учётом обратного прокси (X-Forwarded-For)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class BotTokenAuthentication(BaseAuthentication):
    """Аутентификация Telegram-ботов по заголовку ``X-Bot-Token`` (ТЗ 6.2, 8.2).

    Возвращает ``(user, AuthToken)``. При невалидном/отозванном токене — 401.
    CSRF не применяется (не SessionAuthentication).
    """

    keyword = "X-Bot-Token"

    def authenticate(self, request):
        plain = request.headers.get(self.keyword)
        if not plain:
            return None
        token = verify_token(plain, ip=client_ip(request))
        if token is None:
            raise AuthenticationFailed("Invalid or inactive bot token")
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword


class BotTokenScheme(OpenApiAuthenticationExtension):
    """Схема безопасности X-Bot-Token для OpenAPI (drf-spectacular)."""

    target_class = "apps.api.authentication.BotTokenAuthentication"
    name = "BotTokenAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Bot-Token"}
