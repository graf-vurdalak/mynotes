import json
from unittest.mock import Mock

import pytest
from django.core.management.base import CommandError

from apps.references.management.commands.import_car_catalog import Command


def test_catalog_loader_fetches_http_json_with_timeout(monkeypatch):
    response = Mock()
    response.json.return_value = [{"brand": "Example"}]
    get = Mock(return_value=response)
    monkeypatch.setattr("apps.references.management.commands.import_car_catalog.requests.get", get)

    result = Command()._load("https://catalog.example.test/cars.json")

    assert result == [{"brand": "Example"}]
    get.assert_called_once_with("https://catalog.example.test/cars.json", timeout=30)
    response.raise_for_status.assert_called_once_with()


def test_catalog_loader_still_accepts_local_json(tmp_path):
    source = tmp_path / "catalog.json"
    source.write_text(json.dumps([{"brand": "Example"}]), encoding="utf-8")

    assert Command()._load(str(source)) == [{"brand": "Example"}]


def test_catalog_loader_wraps_http_errors(monkeypatch):
    get = Mock(side_effect=Exception("request failed"))
    monkeypatch.setattr("apps.references.management.commands.import_car_catalog.requests.get", get)

    with pytest.raises(CommandError, match="Не удалось загрузить каталог"):
        Command()._load("https://catalog.example.test/cars.json")
