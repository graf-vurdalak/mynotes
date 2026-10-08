from django import template
from apps.core.i18n import t as _t

register = template.Library()


@register.simple_tag(name="t")
def translate(key: str, **kwargs) -> str:
    return _t(key, **kwargs)


@register.simple_tag(name="app_name")
def app_name() -> str:
    from apps.core.i18n import t
    return t("app.name", default="Мои записи")
