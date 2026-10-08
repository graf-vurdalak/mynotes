"""HTTP-слой гейтвея для Telegram-ботов (ТЗ 6.2).

Все эндпоинты под ``/api/v1/bot/``: авторизация по ``X-Bot-Token``, rate-limit
``RATELIMIT_API`` (ТЗ 8.4), CSRF не применяется (не сессионная аутентификация).
"""

from __future__ import annotations
from apps.core.i18n import t

import mimetypes
from uuid import uuid4

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django_ratelimit.core import is_ratelimited
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.planner.forms import MAX_UPLOAD_SIZE, detect_upload_type
from apps.notifications.services import bind_chat

from . import handlers
from .authentication import BotTokenAuthentication
from .models import BotUpload
from .serializers import (
    ErrorSerializer,
    IngestRequestSerializer,
    ListResponseSerializer,
    OkResponseSerializer,
    UploadRequestSerializer,
    UploadResponseSerializer,
)

# Расширения только для содержимого, распознанного по сигнатуре (ТЗ 8.4).
_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
    "audio/mp3": ".mp3",
    "video/matroska": ".mkv",
    "text/plain": ".txt",
}


class BotAPIView(APIView):
    authentication_classes = [BotTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def _bind_chat(self, request):
        """Upsert привязки Telegram-чата из заголовков бота (ТЗ 4.2.8/4.3.5, вариант А)."""
        bot = request.headers.get("X-Bot-Name")
        chat_id = request.headers.get("X-Telegram-Chat-Id")
        if bot and chat_id:
            bind_chat(request.user, bot, chat_id)

    def _check_rate(self, request, group: str):
        if is_ratelimited(
            request,
            group=f"bot:{group}",
            key="ip",
            rate=settings.RATELIMIT_API,
            method="ALL",
            increment=True,
        ):
            return Response(
                {"status": "error", "detail": t("api.rate_limited")},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return None


class BotPingView(BotAPIView):
    """POST /api/v1/bot/ping — проверка валидности токена."""

    @extend_schema(
        tags=["bot"], summary=t("api.sum_ping"), request=None,
        responses={200: OkResponseSerializer, 401: OpenApiResponse(description=t("api.err_bad_token"))},
    )
    def post(self, request):
        self._bind_chat(request)
        return Response({"status": "ok", "user": request.user.email})


class BotIngestView(BotAPIView):
    """POST /api/v1/bot/ingest — роутинг module+action → сервис-слой."""

    @extend_schema(
        tags=["bot"], summary=t("api.sum_ingest"),
        request=IngestRequestSerializer,
        responses={
            200: OkResponseSerializer,
            400: ErrorSerializer,
            429: OpenApiResponse(description="Rate limit"),
        },
    )
    def post(self, request):
        self._bind_chat(request)
        limited = self._check_rate(request, "ingest")
        if limited:
            return limited
        body = request.data if isinstance(request.data, dict) else {}
        module = body.get("module")
        action = body.get("action")
        if not module or not action:
            raise ValidationError(t("api.err_need_fields"))
        result = handlers.dispatch(module, action, request.user, body.get("payload") or {})
        return Response(result, status=status.HTTP_200_OK)


class BotUploadView(BotAPIView):
    """POST /api/v1/bot/upload — staged-загрузка файла (фото/аудио), ≤10 МБ (ТЗ 8.4)."""

    @extend_schema(
        tags=["bot"], summary=t("api.sum_upload"),
        request=UploadRequestSerializer,
        responses={200: UploadResponseSerializer, 400: ErrorSerializer},
    )
    def post(self, request):
        self._bind_chat(request)
        limited = self._check_rate(request, "upload")
        if limited:
            return limited
        f = request.FILES.get("file")
        if f is None:
            raise ValidationError(t("api.err_no_file"))
        if f.size > MAX_UPLOAD_SIZE:
            raise ValidationError(t("api.err_file_big"))
        mime = detect_upload_type(f)
        if mime is None:
            raise ValidationError(t("api.err_file_type"))
        ext = _EXT_BY_MIME.get(mime) or mimetypes.guess_extension(mime) or ".bin"
        data = f.read()
        upload = BotUpload.objects.create(
            user=request.user,
            file=SimpleUploadedFile(f"{uuid4().hex}{ext}", data, content_type=mime),
            mime_type=mime,
            extension=ext,
            size_bytes=len(data),
        )
        return Response(
            {"status": "ok", "upload_id": str(upload.id), "mime_type": mime,
             "size": upload.size_bytes},
            status=status.HTTP_200_OK,
        )


class BotReferenceView(BotAPIView):
    """GET /api/v1/bot/references/{type} — справочники для ботов."""

    @extend_schema(
        tags=["bot"], summary=t("api.sum_ref"),
        responses={200: ListResponseSerializer, 404: OpenApiResponse(description=t("api.err_ref_missing"))},
    )
    def get(self, request, ref_type: str):
        limited = self._check_rate(request, f"ref:{ref_type}")
        if limited:
            return limited
        provider = handlers.REFERENCES.get(ref_type)
        if provider is None:
            raise NotFound(t("api.ref_not_found", type=ref_type))
        return Response({"status": "ok", "data": provider(request.user)})
