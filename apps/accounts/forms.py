from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from apps.core.i18n import t
from .models import UserSettings

User = get_user_model()

INPUT = "w-full bg-white border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"

# Часовые пояса для выбора (ТЗ 4.1.2) — РФ + СНГ + UTC; список валидируется zoneinfo
TIMEZONES = [
    "UTC",
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Volgograd",
    "Europe/Astrakhan",
    "Europe/Samara",
    "Europe/Kyiv",
    "Europe/Berlin",
    "Europe/London",
    "Asia/Almaty",
    "Asia/Bishkek",
    "Asia/Yekaterinburg",
    "Asia/Omsk",
    "Asia/Novosibirsk",
    "Asia/Krasnoyarsk",
    "Asia/Irkutsk",
    "Asia/Yakutsk",
    "Asia/Vladivostok",
    "Asia/Magadan",
    "Asia/Sakhalin",
    "Asia/Kamchatka",
]


def _style(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500")
        elif isinstance(widget, (forms.Select, forms.TextInput, forms.EmailInput,
                                 forms.NumberInput, forms.URLInput, forms.PasswordInput)):
            widget.attrs.setdefault("class", INPUT)
    return form


class SignupForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "you@example.com",
            "class": "w-full pl-10 pr-4 py-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition",
        })
    )
    display_name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": t("auth.display_name_ph"),
            "class": "w-full pl-10 pr-4 py-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "••••••••",
            "class": "w-full pl-10 pr-4 py-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition",
        })
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Ревью №7: iexact — Postgres unique case-sensitive, строки в другом
        # регистре достижимы (allauth social); та же семантика, что в ProfileForm.
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(t("settings.email_taken"))
        return email

    def clean_password(self):
        # Валидаторы AUTH_PASSWORD_VALIDATORS (ТЗ 8.1: min 10, common, numeric)
        validate_password(self.cleaned_data.get("password", ""))
        return self.cleaned_data["password"]

    def save(self):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password"]
        display_name = self.cleaned_data.get("display_name", "")
        user = User.objects.create_user(
            email=email,
            password=password,
            display_name=display_name,
        )
        return user


CURRENCIES = ["RUB", "USD", "EUR", "KZT", "UAH", "BYN"]


class ProfileForm(forms.ModelForm):
    """ТЗ 4.1.2: отображаемое имя, email (с повторной верификацией), аватар."""

    new_email = forms.EmailField(
        required=False,
        label=t("settings.email_new"),
        widget=forms.EmailInput(attrs={"placeholder": "new@example.com"}),
    )

    class Meta:
        model = User
        fields = ["display_name", "avatar"]
        widgets = {
            "display_name": forms.TextInput(),
            "avatar": forms.ClearableFileInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean_new_email(self):
        email = self.cleaned_data.get("new_email", "").strip().lower()
        if not email or email == self.instance.email.lower():
            return ""
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(t("settings.email_taken"))
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_email"):
            user.email = self.cleaned_data["new_email"]
            user.email_verified = False
        if commit:
            user.save()
        return user


class AppSettingsForm(forms.ModelForm):
    """Язык/валюта/таймзона/тёмная тема (UserSettings, ТЗ 4.1.2)."""

    class Meta:
        model = UserSettings
        fields = ["language", "default_currency", "timezone", "dark_theme"]
        widgets = {"dark_theme": forms.CheckboxInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ModelCharField даёт plain CharField: .choices до Select-виджета не доходит
        # (пустой <select>) и значения не валидируются — нужны ChoiceField (ТЗ 4.1.2).
        self.fields["language"] = forms.ChoiceField(
            choices=[("ru", t("settings.language.ru"))],
        )
        self.fields["default_currency"] = forms.ChoiceField(
            choices=[(c, f"{c} — {t('settings.currency.' + c)}") for c in CURRENCIES],
        )
        self.fields["timezone"] = forms.ChoiceField(
            choices=[(tz, tz) for tz in TIMEZONES],
        )
        _style(self)

    def clean_timezone(self):
        tz = self.cleaned_data["timezone"]
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            raise forms.ValidationError(t("settings.timezone_invalid"))
        return tz


class RemindersForm(forms.ModelForm):
    """Глобальные сроки авто-напоминаний (ТЗ 4.2.8; долг Этапа 5 — веб-формы UserSettings)."""

    class Meta:
        model = UserSettings
        fields = [
            "reminder_default_minutes",
            "insurance_reminder_days",
            "plan_reminder_days",
            "transport_tax_month",
            "transport_tax_day",
        ]
        widgets = {
            "reminder_default_minutes": forms.NumberInput(),
            "insurance_reminder_days": forms.NumberInput(),
            "plan_reminder_days": forms.NumberInput(),
            "transport_tax_month": forms.Select(),
            "transport_tax_day": forms.NumberInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # IntegerField+Select не наполняет виджет и не валидирует выбор — ChoiceField.
        self.fields["transport_tax_month"] = forms.TypedChoiceField(
            coerce=int,
            empty_value=None,
            choices=[(m, t(f"rep.month.{m}")) for m in range(1, 13)],
        )
        self.fields["reminder_default_minutes"].help_text = t("settings.reminder_default_help")
        _style(self)


class StyledPasswordChangeForm(PasswordChangeForm):
    """Смена пароля в ЛК (ТЗ 4.1.2) — Django-форма с валидаторами из AUTH_PASSWORD_VALIDATORS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("old_password", "new_password1", "new_password2"):
            self.fields[name].widget = forms.PasswordInput(attrs={"placeholder": "•" * 10})
        _style(self)


class IssueTokenForm(forms.Form):
    """Выдача токена бота (ТЗ 4.1.3): имя + необязательный срок действия."""

    name = forms.CharField(
        max_length=100,
        label=t("tokens.name"),
        widget=forms.TextInput(attrs={"placeholder": t("tokens.name_placeholder")}),
    )
    expires_in_days = forms.TypedChoiceField(
        required=False,
        label=t("tokens.expires"),
        coerce=int,
        empty_value=None,
        choices=[
            ("", t("tokens.expires_none")),
            ("30", t("tokens.expires.30")),
            ("90", t("tokens.expires.90")),
            ("365", t("tokens.expires.365")),
        ],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
