from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone


def get_timezone(timezone_name):
    if not timezone_name:
        return timezone.get_default_timezone()
    try:
        return ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return timezone.get_default_timezone()


def get_user_timezone(user):
    try:
        timezone_name = user.settings.timezone
    except (AttributeError, ObjectDoesNotExist):
        return timezone.get_default_timezone()
    return get_timezone(timezone_name)
