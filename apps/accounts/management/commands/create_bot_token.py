from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.tokens import issue_token, revoke_token

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Админский инструмент управления токенами Telegram-ботов: создать / отозвать / показать. "
        "Оригинал токена показывается только один раз при создании (ТЗ 4.1.3, 8.2). "
        "Пользовательский поток — через ЛК /accounts/tokens/ (Этап 7.3); команда остаётся "
        "для выпуска/отзыва токенов администратором с сервера."
    )

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email владельца токена")
        parser.add_argument("name", nargs="?", help="Имя токена (для создания)")
        parser.add_argument("--expires-days", type=int, default=None,
                            help="Срок действия токена в днях (по умолчанию — без срока)")
        parser.add_argument("--revoke", action="store_true",
                            help="Отозвать токен по имени вместо создания")
        parser.add_argument("--list", action="store_true", dest="list_tokens",
                            help="Список токенов пользователя")

    def handle(self, *args, **opts):
        user = User.objects.filter(email=opts["email"]).first()
        if user is None:
            raise CommandError(f"Пользователь не найден: {opts['email']}")

        if opts["list_tokens"]:
            self._list(user)
            return

        if not opts["name"]:
            raise CommandError("Укажите имя токена (или --list)")

        if opts["revoke"]:
            token = user.bot_tokens.filter(name=opts["name"], is_active=True).first()
            if token is None:
                raise CommandError(f"Активный токен «{opts['name']}» не найден")
            revoke_token(token)
            self.stdout.write(self.style.SUCCESS(f"Токен «{opts['name']}» отозван."))
            return

        plain, token = issue_token(user, opts["name"], expires_in_days=opts["expires_days"])
        self.stdout.write(self.style.SUCCESS(f"Создан токен «{token.name}» (id={token.id})."))
        self.stdout.write("⚠️  Сохраните сейчас — он больше не показывается:")
        self.stdout.write(self.style.WARNING(plain))

    def _list(self, user):
        tokens = user.bot_tokens.order_by("-created_at")
        if not tokens:
            self.stdout.write("Токенов нет.")
            return
        for tok in tokens:
            flag = "активен" if tok.is_active else "отозван"
            last = tok.last_used_at.strftime("%Y-%m-%d %H:%M") if tok.last_used_at else "—"
            self.stdout.write(
                f"- {tok.name} · {flag} · создан {tok.created_at:%Y-%m-%d} · исп. {last}"
            )
