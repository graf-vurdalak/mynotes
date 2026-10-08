"""Точка входа бота Записной книжки (aiogram 3.x, long polling).

Доменные команды (`/tasks`, `/newtask`, …) подключаются из ``handlers`` (Этап 4.5);
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
from telegram_bots.planner_bot.handlers import register_handlers


def build_router(store: ConfigStore) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(message: Message):
        if not store.list(message.chat.id):
            await message.answer(t("bot.start.planner_no_server"))
            return
        await message.answer(t("bot.start.planner"))

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(t("bot.help.planner"))

    register_server_commands(router, store)
    register_handlers(router, store)
    return router


def main() -> None:
    os.environ.setdefault("BOT_MODULE", "planner")
    store = ConfigStore()
    dp = build_dispatcher([build_router(store)])
    run_polling(create_bot(env_token("TELEGRAM_PLANNER_BOT_TOKEN")), dp)


if __name__ == "__main__":  # pragma: no cover
    main()
