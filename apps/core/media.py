from django.apps import apps

# Реестр FileField-в приложения: (model_label, field, owner_resolver).
# Используется authorized-прокси /media/<path> для проверки принадлежности файла
# конкретному пользователю (защита от угадывания ключей другим пользователем).
# Поле file-field хранит относительный ключ — сверка exact-match, provider-specific
# URL в БД не записываются (План MinIO: переносимость без изменения ключей).
MEDIA_FILE_OWNERS = [
    ("accounts.User", "avatar", lambda record: record.pk),
    ("vehicles.Vehicle", "photo", lambda record: record.user_id),
    ("vehicles.FuelEntry", "receipt_photo", lambda record: record.user_id),
    ("vehicles.Purchase", "photo", lambda record: record.user_id),
    # ServicePhoto не наследует OwnedModel — владелец через запись сервиса.
    ("vehicles.ServicePhoto", "image", lambda record: record.service.user_id),
    ("vehicles.Fine", "photo", lambda record: record.user_id),
    ("vehicles.Insurance", "photo", lambda record: record.user_id),
    ("planner.EventAttachment", "file", lambda record: record.user_id),
    ("api.BotUpload", "file", lambda record: record.user_id),
]


def file_owner_ids(path):
    """Возвращает set id пользователей — владельцев записи с данным ключом файла.

    Пустой set: файла ни в одной записи нет или его запись удалена (soft-delete) —
    прокси отдаёт 404 и не раскрывает существование объекта.
    """
    owners = set()
    for label, field, resolver in MEDIA_FILE_OWNERS:
        model = apps.get_model(label)
        query = {field: path}
        if hasattr(model, "is_deleted"):
            query["is_deleted"] = False
        for record in model.objects.filter(**query):
            owners.add(resolver(record))
    return owners
