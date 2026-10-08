from datetime import date
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.api import handlers
from apps.api.authentication import client_ip


def test_required_optional_and_string_values():
    with pytest.raises(ValidationError):
        handlers._req({}, "title")

    assert handlers._opt({}, "limit", 10) == 10
    assert handlers._str({"value": None}, "value") == ""
    assert handlers._str({"value": "title"}, "value", required=True) == "title"


def test_integer_decimal_and_boolean_values():
    assert handlers._int({"value": "12"}, "value", required=True) == 12
    assert handlers._int({}, "value") is None
    with pytest.raises(ValidationError):
        handlers._int({"value": "12.5"}, "value")

    with pytest.raises(ValidationError):
        handlers._dec({"value": "not-a-number"}, "value")

    assert handlers._bool({"value": "ДА"}, "value") is True
    assert handlers._bool({"value": "no"}, "value") is False
    assert handlers._bool({"value": 1}, "value") is True


def test_date_and_datetime_values():
    today = timezone.localdate()
    assert handlers._date_val({}, "date") == today
    assert handlers._date_val({"date": date(2026, 10, 1)}, "date") == date(2026, 10, 1)
    assert handlers._date_val({"date": "2026-10-01"}, "date") == date(2026, 10, 1)
    with pytest.raises(ValidationError):
        handlers._date_val({"date": "tomorrow"}, "date")

    assert handlers._dt_val({}, "date") is None
    with pytest.raises(ValidationError):
        handlers._dt_val({"date": "not-a-datetime"}, "date")
    naive = handlers._dt_val({"date": "2026-10-01T12:00:00"}, "date")
    assert timezone.is_aware(naive)


def test_currency_falls_back_when_user_has_no_settings():
    assert handlers._currency(SimpleNamespace()) == "RUB"


def test_api_client_ip_uses_forwarded_header_or_remote_addr():
    forwarded = SimpleNamespace(
        META={"HTTP_X_FORWARDED_FOR": " 198.51.100.7, 10.0.0.4", "REMOTE_ADDR": "127.0.0.1"}
    )
    direct = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

    assert client_ip(forwarded) == "198.51.100.7"
    assert client_ip(direct) == "127.0.0.1"
