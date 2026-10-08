"""Сервис 2FA (ТЗ 4.1.2, 5.2, 8.1): TOTP-устройства и резервные коды.

Реализация на django-otp (otp_totp/otp_static): БД хранит секрет TOTP и
одноразовые статические коды; проверка — ``verify_token`` с встроенным
throttling и защитой от повторного использования TOTP-токена (``last_t``).
"""

from __future__ import annotations

import io

import qrcode
import qrcode.image.svg
from django.db import transaction
from django_otp import devices_for_user
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

BACKUP_CODE_COUNT = 10


def get_device(user) -> TOTPDevice | None:
    """Подтверждённое TOTP-устройство пользователя (или None)."""
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def is_enabled(user) -> bool:
    return get_device(user) is not None


def begin_enable(user, name: str = "default") -> TOTPDevice:
    """Неподтверждённое устройство для мастера включения (старые черновики сбрасываются)."""
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    return TOTPDevice.objects.create(user=user, name=name, confirmed=False)


def get_unconfirmed_device(user, pk) -> TOTPDevice | None:
    if not pk:
        return None
    return TOTPDevice.objects.filter(user=user, pk=pk, confirmed=False).first()


def provisioning_qr(device: TOTPDevice) -> str:
    """SVG-разметка QR для otpauth-URI (без Pillow, инлайн в шаблон)."""
    image = qrcode.make(
        device.config_url, image_factory=qrcode.image.svg.SvgPathImage
    )
    buf = io.BytesIO()
    image.save(buf)
    svg = buf.getvalue().decode("utf-8")
    # для встраивания в HTML убираем XML-декларацию (браузеры игнорируют, но чище без неё)
    return svg[svg.index("<svg"):]


def provisioning_secret(device: TOTPDevice) -> str:
    """Base32-секрет для ручного ввода."""
    from base64 import b32encode
    from binascii import unhexlify

    return b32encode(unhexlify(device.key.encode())).decode()


def confirm_device(device: TOTPDevice, token: str) -> bool:
    if device.confirmed:
        return True
    if device.verify_token(token):
        device.confirmed = True
        device.save()
        return True
    return False


def generate_backup_codes(user, count: int = BACKUP_CODE_COUNT) -> list[str]:
    """Пересоздаёт пул резервных кодов otp_static; оригиналы возвращаются ровно один раз."""
    device, _ = StaticDevice.objects.get_or_create(user=user, name="backup")
    if not device.confirmed:
        device.confirmed = True
        device.save()
    device.token_set.all().delete()
    codes: list[str] = []
    seen = set()
    while len(codes) < count:
        code = StaticToken.random_token()
        if code in seen:
            continue
        seen.add(code)
        StaticToken.objects.create(device=device, token=code)
        codes.append(code)
    return codes


def backup_codes_left(user) -> int:
    device = StaticDevice.objects.filter(user=user, confirmed=True).first()
    return device.token_set.count() if device else 0


def verify_any_token(user, token: str):
    """Проверяет TOTP-код или резервный код (расходует его); None при неудаче."""
    with transaction.atomic():
        for device in devices_for_user(user, confirmed=True, for_verify=True):
            if device.verify_token(token):
                return device
    return None


def disable(user) -> None:
    """Полное выключение 2FA: удаляет устройства и коды (аудит-запись — на уровне вызова)."""
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
