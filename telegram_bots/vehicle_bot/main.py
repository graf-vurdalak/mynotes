"""Точка входа бота Бортжурнала (aiogram 3.x, long polling).

Доменные команды (`/fuel`, `/purchase`, …) подключаются из ``handlers`` (Этап 4.4);
здесь — каркас: `/start`, `/help` и команды мульти-серверности.
"""

from __future__ import annotations

import os

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from telegram_bots.common.bot_runtime import build_dispatcher, create_bot, env_token, run_polling
from telegram_bots.common.config_store import ConfigStore
from telegram_bots.common.server_commands import register_server_commands
from telegram_bots.common.texts import t
from telegram_bots.vehicle_bot.handlers import register_handlers


def build_router(store: ConfigStore) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(message: Message):
        hint = "" if store.list(message.chat.id) else f"\n\n{t('bot.start.add_hint')}"
        await message.answer(t("bot.vehicle.start") + hint)

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(t("bot.vehicle.help"))

    register_server_commands(router, store)
    register_handlers(router, store)
    return router


def main() -> None:
    os.environ.setdefault("BOT_MODULE", "vehicle")
    store = ConfigStore()
    bot = create_bot(env_token("TELEGRAM_VEHICLE_BOT_TOKEN"))
    dp = build_dispatcher([build_router(store)])
    run_polling(bot, dp)


if __name__ == "__main__":
    main()
