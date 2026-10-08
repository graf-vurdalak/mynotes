"""Общая сборка Bot/Dispatcher и запуск long-polling (ТЗ 7, aiogram 3.x)."""

from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


def create_bot(token: str) -> Bot:
    if not token:
        raise RuntimeError("Не задан токен бота (TELEGRAM_*_BOT_TOKEN)")
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher(routers) -> Dispatcher:
    dp = Dispatcher()
    for router in routers:
        dp.include_router(router)
    return dp


def run_polling(bot: Bot, dp: Dispatcher) -> None:
    async def _start():
        try:
            await dp.start_polling(bot)
        finally:
            await bot.session.close()

    asyncio.run(_start())


def env_token(name: str) -> str:
    return os.environ.get(name, "")
