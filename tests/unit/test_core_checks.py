from apps.core.checks import check_fernet_key


def test_production_requires_fernet_key(settings):
    settings.DEBUG = False
    settings.FERNET_KEY = ""

    errors = check_fernet_key(None)

    assert [error.id for error in errors] == ["core.E001"]


def test_development_or_configured_production_passes(settings):
    settings.DEBUG = True
    settings.FERNET_KEY = ""
    assert check_fernet_key(None) == []

    settings.DEBUG = False
    settings.FERNET_KEY = "test-key"
    assert check_fernet_key(None) == []
