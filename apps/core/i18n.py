import logging
from functools import lru_cache
from pathlib import Path

import environ

logger = logging.getLogger(__name__)
env = environ.Env()

DEFAULT_LANG_FILE = Path(__file__).parent.parent.parent / "locale" / "ru_ru.lang"


def _parse_lang_file(filepath: Path) -> dict[str, str]:
    translations: dict[str, str] = {}
    if not filepath.exists():
        logger.warning("Lang file not found: %s", filepath)
        return translations
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                translations[key.strip()] = value.strip()
    return translations


@lru_cache(maxsize=4)
def load_translations(lang_file: Path | None = None) -> dict[str, str]:
    filepath = lang_file or DEFAULT_LANG_FILE
    return _parse_lang_file(filepath)


def t(key: str, **kwargs) -> str:
    translations = load_translations()
    value = translations.get(key, key)
    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return value


def get_translation_dict() -> dict[str, str]:
    return load_translations()
