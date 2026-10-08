"""Общие для обоих ботов команды мульти-серверности (ТЗ 7.1/7.2).

``/servers`` — список + переключение активного, ``/addserver`` — мастер
(имя → URL → токен → ping-проверка), ``/removeserver`` — удаление.
Регистрируются на Router конкретного бота: ``register_server_commands(router, store)``.
"""

from __future__ import annotations

from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .api_client import BotAPIClient, BotAPIError
from .config_store import ConfigStore
from .texts import t


class AddServerStates(StatesGroup):
    name = State()
    url = State()
    token = State()


def _servers_keyboard(store: ConfigStore, chat_id) -> InlineKeyboardMarkup:
    rows = []
    for inst in store.list(chat_id):
        mark = "✅ " if inst.is_active else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{inst.name}", callback_data=f"srv:set:{inst.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def register_server_commands(router: Router, store: ConfigStore) -> None:
    @router.message(Command("servers"))
    async def cmd_servers(message: Message):
        kb = _servers_keyboard(store, message.chat.id)
        if not kb:
            await message.answer(t("bot.servers.empty"))
            return
        await message.answer(t("bot.servers.title"), reply_markup=kb)

    @router.callback_query(F.data.startswith("srv:set:"))
    async def cb_set(callback: CallbackQuery):
        iid = callback.data.split(":", 2)[2]
        inst = store.get(callback.message.chat.id, iid)
        if inst is None:
            await callback.answer(t("bot.server.removed"))
            return
        store.set_active(callback.message.chat.id, iid)
        await callback.answer(t("bot.server.switched", name=inst.name))
        kb = _servers_keyboard(store, callback.message.chat.id)
        await callback.message.edit_reply_markup(reply_markup=kb)

    @router.callback_query(F.data.startswith("srv:del:"))
    async def cb_remove(callback: CallbackQuery):
        iid = callback.data.split(":", 2)[2]
        store.remove(callback.message.chat.id, iid)
        await callback.answer(t("bot.server.removed"))
        kb = _servers_keyboard(store, callback.message.chat.id)
        await callback.message.edit_reply_markup(reply_markup=kb)

    @router.message(Command("addserver"))
    async def cmd_addserver(message: Message, state: FSMContext):
        await state.set_state(AddServerStates.name)
        await message.answer(t("bot.addserver.ask_name"))

    @router.message(AddServerStates.name)
    async def add_name(message: Message, state: FSMContext):
        await state.update_data(name=message.text.strip())
        await state.set_state(AddServerStates.url)
        await message.answer(t("bot.addserver.ask_url"))

    @router.message(AddServerStates.url)
    async def add_url(message: Message, state: FSMContext):
        url = message.text.strip()
        if not url.startswith(("http://", "https://")):
            await message.answer(t("bot.addserver.bad_url"))
            return
        await state.update_data(url=url)
        await state.set_state(AddServerStates.token)
        await message.answer(t("bot.addserver.ask_token"))

    @router.message(AddServerStates.token)
    async def add_token(message: Message, state: FSMContext):
        data = await state.get_data()
        token = message.text.strip()
        client = BotAPIClient(data["url"], token, chat_id=message.chat.id)
        try:
            await client.ping()
        except BotAPIError as exc:
            await client.aclose()
            await message.answer(t("bot.addserver.ping_fail", status=exc.status, detail=exc.detail))
            await state.clear()
            return
        except Exception:
            await client.aclose()
            await message.answer(t("bot.addserver.ping_fail", status="—", detail="network"))
            await state.clear()
            return
        await client.aclose()
        iid = uuid4().hex[:8]
        store.add(message.chat.id, iid, data["name"], data["url"], token)
        await state.clear()
        await message.answer(t("bot.addserver.added", name=data["name"]))

    @router.message(Command("removeserver"))
    async def cmd_removeserver(message: Message):
        rows = []
        for inst in store.list(message.chat.id):
            rows.append([InlineKeyboardButton(
                text=inst.name, callback_data=f"srv:del:{inst.id}")])
        if not rows:
            await message.answer(t("bot.servers.empty"))
            return
        await message.answer(t("bot.removeserver.title"),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
