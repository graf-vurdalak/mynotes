from apps.core.i18n import t
import re

from django import forms
from django.core.exceptions import ValidationError

from .models import Comment, Event, Project, Status
from .services import WEEKDAY_NAMES

TAG_SPLIT = re.compile(r"[,\s]+")
WEEKDAY_CHOICES = list(zip(WEEKDAY_NAMES, [t(f"date.wd.{i}") for i in range(1, 8)]))

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # ТЗ 8.4: до 10 МБ на файл
MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"RIFF", "image/webp-or-wav"),
    (b"\x1a\x45\xdf\xa3", "video/matroska"),
    (b"OggS", "audio/ogg"),
    (b"\xff\xf1", "audio/aac"),
    (b"\xff\xf8", "audio/mp3"),
    (b"\xd0\xcf\x11\xe0", "application/msword"),
]
DENY_PREFIXES = (b"<", b"<!", b"\xef\xbb\xbf<")


def detect_upload_type(f) -> str | None:
    """MIME по сигнатуре содержимого; запрещает HTML/SVG/скрипты (ТЗ 8.4)."""
    pos = f.tell() if hasattr(f, "tell") else 0
    head = f.read(16)
    f.seek(pos)
    for magic, mime in MAGIC_SIGNATURES:
        if head.startswith(magic):
            return mime
    if head.startswith(DENY_PREFIXES):
        return None
    if all(32 <= b < 127 or b in (9, 10, 13) for b in head):
        return "text/plain"
    return "application/octet-stream"


class TagsField(forms.CharField):
    """Теги через запятую/пробел → list[str]."""

    def to_python(self, value):
        if not value:
            return []
        return [t.lstrip("#").strip() for t in TAG_SPLIT.split(value) if t.strip()]

    def prepare_value(self, value):
        if isinstance(value, (list, tuple)):
            return ", ".join(value)
        return value or ""


class PlannerFormMixin:
    """Общий стиль полей + user-скоуп."""

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            css = "form-select" if isinstance(widget, forms.Select) else "form-input"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()


class RecurrenceMixin(forms.Form):
    """Повторение (ТЗ 4.3.2) для событий и задач — единая реализация.

    Наследуется от Form, чтобы метакласс собрал объявленные поля в дочерних
    ModelForm. Порядок важен: recurrence_byday/interval/until/count
    очищаются до clean_recurrence.
    """

    recurrence = forms.ChoiceField(
        required=False,
        label=t("pl.recurrence"),
        choices=[
            ("", t("pl.rec_none")),
            ("daily", t("pl.rec_daily")),
            ("weekly", t("pl.rec_weekly")),
            ("monthly", t("pl.rec_monthly")),
            ("yearly", t("pl.rec_yearly")),
            ("weekdays", t("pl.rec_byday")),
            ("interval", t("pl.rec_interval")),
        ],
    )
    recurrence_byday = forms.MultipleChoiceField(
        required=False, label=t("pl.rec_days"), choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    recurrence_interval = forms.IntegerField(
        required=False, label=t("pl.rec_interval_days"), min_value=2
    )
    recurrence_until = forms.DateField(
        required=False, label=t("pl.rec_until"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    recurrence_count = forms.IntegerField(
        required=False, label=t("pl.rec_count"), min_value=1
    )

    def build_recurrence_rule(self):
        """Сборка RRULE-подмножества из очищенных полей (вызывать из form.clean())."""
        if not self.is_bound:
            return ""
        raw = self.cleaned_data.get("recurrence", "")
        valid = {c[0] for c in self.fields["recurrence"].choices}
        if raw not in valid:
            self.add_error("recurrence", ValidationError(t("pl.rec_invalid_choice")))
            return ""
        if raw in {"", "daily", "weekly", "monthly", "yearly"}:
            return raw
        if raw == "weekdays":
            days = [d for d in self.cleaned_data.get("recurrence_byday", []) if d in WEEKDAY_NAMES]
            if not days:
                self.add_error("recurrence", ValidationError(t("pl.rec_days_required")))
                return ""
            return "weekly:BYDAY=" + ",".join(days)
        if raw == "interval":
            n = self.cleaned_data.get("recurrence_interval")
            if not n or n < 2:
                self.add_error("recurrence", ValidationError(t("pl.rec_interval_min")))
                return ""
            return f"FREQ=DAILY;INTERVAL={n}"
        self.add_error("recurrence", ValidationError(t("pl.rec_unknown")))
        return ""

    def apply_recurrence(self, obj):
        obj.recurrence_rule = getattr(self, "_recurrence_rule", "")
        until = self.cleaned_data.get("recurrence_until")
        import datetime as dt

        from django.utils import timezone

        obj.recurrence_end = (
            timezone.make_aware(dt.datetime.combine(until, dt.time(23, 59))) if until else None
        )
        obj.recurrence_count = self.cleaned_data.get("recurrence_count")

    def prefill_recurrence(self):
        rule = self.instance.recurrence_rule or ""
        choice = _recurrence_choice(rule)
        self.initial["recurrence"] = choice
        if choice == "weekdays":
            self.initial["recurrence_byday"] = rule.split("BYDAY=", 1)[1].split(",")
        elif choice == "interval":
            for part in rule.split(";"):
                if part.startswith("INTERVAL="):
                    self.initial["recurrence_interval"] = int(part.split("=", 1)[1])
        if self.instance.recurrence_end:
            self.initial["recurrence_until"] = self.instance.recurrence_end.astimezone().date()
        self.initial["recurrence_count"] = self.instance.recurrence_count


class EventForm(RecurrenceMixin, PlannerFormMixin, forms.ModelForm):
    """Форма события личного раздела (макет 17)."""

    date_start = forms.DateField(
        label=t("pl.date_start"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    time_start = forms.TimeField(
        required=False,
        label=t("pl.time_start"),
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    date_end = forms.DateField(
        required=False,
        label=t("pl.date_end"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    time_end = forms.TimeField(
        required=False,
        label=t("pl.time_end"),
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    all_day = forms.BooleanField(required=False, label=t("pl.all_day"))
    tags = TagsField(required=False, label=t("pl.tags"))
    reminder_enabled = forms.BooleanField(required=False, label=t("pl.reminder"))
    reminder_minutes = forms.IntegerField(
        required=False, label=t("pl.reminder_minutes"), min_value=0
    )

    class Meta:
        model = Event
        fields = ["title", "description", "location", "project", "priority", "tags"]

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(
            user=user, scope__code="personal", is_deleted=False, is_archived=False
        )
        self.fields["project"].required = False
        self.fields["project"].empty_label = t("pl.no_project")
        if not self.instance._state.adding:
            import datetime as dt

            local = self.instance.start_at.astimezone() if self.instance.start_at else None
            if local:
                self.initial["date_start"] = local.strftime("%Y-%m-%d")
                if local.time() != dt.time(0, 0):
                    self.initial["time_start"] = local.strftime("%H:%M")
                    self.initial["all_day"] = False
                else:
                    self.initial["all_day"] = True
            if self.instance.end_at:
                lend = self.instance.end_at.astimezone()
                self.initial["date_end"] = lend.strftime("%Y-%m-%d")
                self.initial["time_end"] = lend.strftime("%H:%M")
            self.prefill_recurrence()
            if self.instance.reminder_minutes_before is not None:
                self.initial["reminder_enabled"] = self.instance.reminder_minutes_before != 0
                self.initial["reminder_minutes"] = self.instance.reminder_minutes_before or None

    def clean(self):
        cleaned = super().clean()
        self._recurrence_rule = self.build_recurrence_rule()
        from django.utils import timezone
        import datetime as dt

        d_start = cleaned.get("date_start")
        if d_start:
            if cleaned.get("all_day"):
                cleaned["time_start"] = None
            t_start = cleaned.get("time_start") or dt.time(0, 0)
            start_dt = timezone.make_aware(dt.datetime.combine(d_start, t_start))
            cleaned["_start_dt"] = start_dt
            d_end = cleaned.get("date_end")
            if d_end:
                t_end = None if cleaned.get("all_day") else (cleaned.get("time_end") or dt.time(23, 59))
                end_dt = timezone.make_aware(dt.datetime.combine(d_end, t_end))
                if end_dt < start_dt:
                    raise ValidationError(t("pl.end_before_start"))
                cleaned["_end_dt"] = end_dt
        return cleaned

    def save(self, commit=True):
        from .services import get_scope

        cleaned = self.cleaned_data
        event = super().save(commit=False)
        event.user = self.user
        event.scope = get_scope(self.user, "personal")
        event.event_type = "meeting" if cleaned.get("location") else "reminder"
        event.start_at = cleaned.get("_start_dt")
        event.end_at = cleaned.get("_end_dt")
        self.apply_recurrence(event)
        # Семантика модели: NULL — глобальный дефолт, 0 — выключено
        if cleaned.get("reminder_enabled"):
            minutes = cleaned.get("reminder_minutes")
            event.reminder_minutes_before = minutes if minutes else None
        else:
            event.reminder_minutes_before = 0
        if commit:
            event.save()
        return event


class TaskForm(RecurrenceMixin, PlannerFormMixin, forms.ModelForm):
    """Форма задачи рабочего раздела (макет 18)."""

    date_start = forms.DateField(
        required=False, label=t("pl.date_start"), widget=forms.DateInput(attrs={"type": "date"})
    )
    date_due = forms.DateField(
        required=False, label=t("pl.due_at"), widget=forms.DateInput(attrs={"type": "date"})
    )
    time_due = forms.TimeField(
        required=False, label=t("pl.due_time"), widget=forms.TimeInput(attrs={"type": "time"})
    )
    estimated_hours = forms.DecimalField(
        required=False, label=t("pl.estimate_hours"), min_value=0, decimal_places=1
    )
    actual_hours = forms.DecimalField(
        required=False, label=t("pl.actual_hours"), min_value=0, decimal_places=1
    )
    tags = TagsField(required=False, label=t("pl.tags"))

    class Meta:
        model = Event
        fields = ["title", "description", "project", "status", "priority", "tags"]

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        from .services import get_scope

        self.work_scope = get_scope(user, "work")
        self.fields["project"].queryset = Project.objects.filter(
            user=user, scope=self.work_scope, is_deleted=False, is_archived=False
        )
        self.fields["project"].required = False
        self.fields["project"].empty_label = t("pl.no_project")
        self.fields["status"].queryset = Status.objects.filter(
            user=user, is_deleted=False
        ).order_by("sort_order")
        self.fields["status"].empty_label = None
        if not self.instance._state.adding:
            self._prefill()

    def _prefill(self):
        if self.instance.start_at:
            self.initial["date_start"] = self.instance.start_at.astimezone().strftime("%Y-%m-%d")
        if self.instance.due_at:
            local = self.instance.due_at.astimezone()
            self.initial["date_due"] = local.strftime("%Y-%m-%d")
            self.initial["time_due"] = local.strftime("%H:%M")
        if self.instance.estimated_minutes:
            self.initial["estimated_hours"] = round(self.instance.estimated_minutes / 60, 1)
        if self.instance.actual_minutes:
            self.initial["actual_hours"] = round(self.instance.actual_minutes / 60, 1)
        self.prefill_recurrence()
        self.initial["tags"] = self.instance.tags

    def clean(self):
        cleaned = super().clean()
        self._recurrence_rule = self.build_recurrence_rule()
        from django.utils import timezone
        import datetime as dt

        if cleaned.get("date_start"):
            cleaned["_start_dt"] = timezone.make_aware(
                dt.datetime.combine(cleaned["date_start"], dt.time(9, 0))
            )
        if cleaned.get("date_due"):
            t = cleaned.get("time_due") or dt.time(18, 0)
            cleaned["_due_dt"] = timezone.make_aware(dt.datetime.combine(cleaned["date_due"], t))
        return cleaned

    def save(self, commit=True):
        cleaned = self.cleaned_data
        task = super().save(commit=False)
        task.user = self.user
        task.scope = self.work_scope
        task.event_type = "task"
        task.start_at = cleaned.get("_start_dt")
        task.due_at = cleaned.get("_due_dt")
        self.apply_recurrence(task)
        if cleaned.get("estimated_hours") is not None:
            task.estimated_minutes = int(cleaned["estimated_hours"] * 60)
        if cleaned.get("actual_hours") is not None:
            task.actual_minutes = int(cleaned["actual_hours"] * 60)
        if task.status is None:
            from .services import default_status_for

            task.status = default_status_for(self.user)
        if commit:
            task.save()
        return task


def _recurrence_choice(rule: str) -> str:
    if not rule:
        return ""
    if rule in {"daily", "weekly", "monthly", "yearly"}:
        return rule
    if rule.startswith("weekly:BYDAY"):
        return "weekdays"
    if rule.startswith("FREQ="):
        return "interval"
    return ""


class ProjectForm(PlannerFormMixin, forms.ModelForm):
    """Форма проекта (макет 20)."""

    scope_choice = forms.ChoiceField(
        label=t("pl.scope_field"),
        choices=[("personal", t("pl.pick_personal")), ("work", t("pl.pick_work"))],
    )

    class Meta:
        model = Project
        fields = ["title", "description", "color", "is_archived"]

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        if not self.instance._state.adding:
            self.initial["scope_choice"] = self.instance.scope.code

    def clean_color(self):
        color = self.cleaned_data.get("color", "")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color or ""):
            return "#3B82F6"
        return color.upper()

    def save(self, commit=True):
        from .services import get_scope

        project = super().save(commit=False)
        project.user = self.user
        project.scope = get_scope(self.user, self.cleaned_data["scope_choice"])
        if commit:
            project.save()
        return project


class StatusForm(PlannerFormMixin, forms.ModelForm):
    """Переименование/цвет/порядок статуса (макет 21)."""

    class Meta:
        model = Status
        fields = ["name", "color", "sort_order"]

    def clean_color(self):
        color = self.cleaned_data.get("color", "")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color or ""):
            raise ValidationError(t("pl.color_format"))
        return color.upper()


class MultiFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """Список UploadedFile вместо одного файла (паттерн vehicles/forms.py)."""

    def to_python(self, data):
        if data in self.empty_values:
            return []
        if isinstance(data, (list, tuple)):
            return list(data)
        return [data]

    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages["required"], code="required")


class CommentForm(PlannerFormMixin, forms.ModelForm):
    """Комментарий к задаче + вложения с валидацией (макет 19, ТЗ 8.4)."""

    files = MultiFileField(
        required=False,
        label=t("pl.attachments"),
        widget=MultiFileInput(attrs={"multiple": True, "class": "form-input"}),
    )

    class Meta:
        model = Comment
        fields = ["text"]

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["text"].widget.attrs["rows"] = 2
        self.fields["text"].widget.attrs["placeholder"] = t("pl.comment_ph")

    def clean_files(self):
        raw = self.files.getlist("files")
        for f in raw:
            if f.size > MAX_UPLOAD_SIZE:
                raise ValidationError(t("pl.file_too_large", name=f.name))
            if detect_upload_type(f) is None:
                raise ValidationError(t("pl.file_bad_type", name=f.name))
        return raw

    def save(self, commit=True):
        comment = super().save(commit=False)
        comment.user = self.user
        comment.author = self.user
        if commit:
            comment.save()
        return comment
