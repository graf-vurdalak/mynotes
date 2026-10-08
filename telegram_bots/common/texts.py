"""Локализация текстов ботов (ТЗ 10).

Собственный лёгкий загрузчик ``.lang`` (тот же формат, что и ``apps/core/i18n.py``),
но без зависимости от Django/Redis — процесс бота поднимает только словарь из
``locale/ru_ru.lang``. Ключи ботов — секция ``bot.*``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

LANG_FILE = Path(__file__).resolve().parents[2] / "locale" / "ru_ru.lang"


@lru_cache(maxsize=4)
def _load(path: str | None = None) -> dict[str, str]:
    filepath = Path(path) if path else LANG_FILE
    out: dict[str, str] = {}
    if not filepath.exists():
        return out
    for line in filepath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def t(key: str, **kwargs) -> str:
    value = _load().get(key, key)
    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return value
