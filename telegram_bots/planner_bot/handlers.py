"""Доменные команды бота Записной книжки (ТЗ 7.4): /scope, /events, /tasks, /projects,
/search, /quick, мастера /newtask и /newevent (через общий ``flow``)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from telegram_bots.common import flow, inline, parsers
from telegram_bots.common.api_client import BotAPIClient, BotAPIError
from telegram_bots.common.config_store import ConfigStore
from telegram_bots.common.flow import Field
from telegram_bots.common.texts import t
from telegram_bots.planner_bot.quick import interpret


def _rows(items, fmt, prefix):
    return [[InlineKeyboardButton(text=fmt(x), callback_data=f"{prefix}:{x['id']}")]
            for x in items]


def register_handlers(router: Router, store: ConfigStore) -> None:
    async def get_client(message: Message) -> BotAPIClient | None:
        inst = store.active(message.chat.id)
        return BotAPIClient(inst.url, inst.token, chat_id=message.chat.id) if inst else None

    async def get_vehicle(message, client):  # не используется (module != vehicle)
        return None

    # --- мастера ---
    flow.register("create_task", "planner", [
        Field("title", "bot.task.title", parsers.to_text),
        Field("description", "bot.task.description", parsers.to_text, required=False),
        Field("priority", "bot.task.priority", parsers.to_text, required=False),
        Field("due_at", "bot.task.due", parsers.to_date, required=False),
        Field("tags", "bot.task.tags", parsers.to_tags, required=False),
    ])
    flow.register("create_event", "planner", [
        Field("title", "bot.event.title", parsers.to_text),
        Field("start_at", "bot.event.start", parsers.to_datetime_field, required=False),
        Field("location", "bot.event.location", parsers.to_text, required=False),
        Field("priority", "bot.event.priority", parsers.to_text, required=False),
        Field("tags", "bot.event.tags", parsers.to_tags, required=False),
    ])
    flow.add_collect_handlers(router, get_client, get_vehicle)

    async def _start(message, state, action):
        if not store.active(message.chat.id):
            await message.answer(t("bot.no_server"))
            return
        await flow.start(message, state, action)

    @router.message(Command("newtask"))
    async def cmd_newtask(message: Message, state: FSMContext):
        await _start(message, state, "create_task")

    @router.message(Command("newevent"))
    async def cmd_newevent(message: Message, state: FSMContext):
        await _start(message, state, "create_event")

    # --- скоуп ---
    @router.message(Command("scope"))
    async def cmd_scope(message: Message):
        cur = store.get_kv(message.chat.id, "scope") or "personal"
        rows = [[InlineKeyboardButton(text=t("bot.scope.label", name="Личное"),
                                      callback_data="scope:personal")],
                [InlineKeyboardButton(text=t("bot.scope.label", name="Рабочее"),
                                      callback_data="scope:work")]]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await message.answer(t("bot.scope.title", current=cur), reply_markup=kb)

    @router.callback_query(F.data.startswith("scope:"))
    async def cb_scope(callback: CallbackQuery):
        code = callback.data.split(":", 1)[1]
        store.set_kv(callback.message.chat.id, "scope", code)
        await callback.answer(t("bot.scope.set", code=code))

    # --- списки ---
    async def _ingest(message, action, payload=None):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return None
        try:
            return await client.ingest("planner", action, payload or {})
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return None

    @router.message(Command("events"))
    async def cmd_events(message: Message):
        res = await _ingest(message, "list_events", {"scope": "personal"})
        if res is None:
            return
        data = res.get("data", [])
        lines = [t("bot.event.row", date=_fmt_dt(x["start"]), title=x["title"]) for x in data]
        await message.answer("\n".join(lines) or t("bot.events.empty"))

    @router.message(Command("tasks"))
    async def cmd_tasks(message: Message):
        res = await _ingest(message, "list_tasks")
        if res is None:
            return
        data = res.get("data", [])
        lines = [t("bot.task.row", status=x["status"] or "—", title=x["title"]) for x in data]
        await message.answer("\n".join(lines) or t("bot.tasks.empty"))

    @router.message(Command("projects"))
    async def cmd_projects(message: Message):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        try:
            refs = await client.reference("projects")
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        data = refs.get("data", [])
        lines = [t("bot.project.row", title=p["title"], scope=p["scope"]) for p in data]
        await message.answer("\n".join(lines) or t("bot.projects.empty"))

    @router.message(Command("search"))
    async def cmd_search(message: Message, command: CommandObject):
        query = (command.args or "").strip()
        if not query:
            await message.answer(t("bot.search.usage"))
            return
        res = await _ingest(message, "search", {"query": query})
        if res is None:
            return
        data = res.get("data", [])
        lines = [t("bot.search.row", scope=x["scope"], title=x["title"]) for x in data]
        await message.answer("\n".join(lines) or t("bot.search.empty"))

    # --- быстрая запись ---
    @router.message(Command("quick"))
    async def cmd_quick(message: Message, command: CommandObject):
        text = (command.args or "").strip()
        if not text:
            await message.answer(t("bot.quick.usage_planner"))
            return
        parsed = interpret(text)
        if parsed is None:
            await message.answer(t("bot.quick.unrecognized"))
            return
        res = await _ingest(message, parsed["action"], parsed["payload"])
        if res is None:
            return
        await message.answer(t("bot.quick.saved", action=parsed["action"]))

    # --- inline-режим (ТЗ 7.5): «задача:<запрос>» → поиск -----------------
    @router.inline_query()
    async def on_inline(query: InlineQuery):
        user_id = query.from_user.id if query.from_user else None
        inst = store.active(user_id)
        if not inst:
            await query.answer(
                [InlineQueryResultArticle(
                    id="hint", title=t("bot.no_server"),
                    input_message_content=InputTextMessageContent(message_text=t("bot.no_server")),
                )], cache_time=1, is_personal=True,
            )
            return
        term = inline.parse_term(query.query)
        client = BotAPIClient(inst.url, inst.token)
        try:
            res = await client.ingest("planner", "search", {"query": term})
        except BotAPIError:
            await client.aclose()
            await query.answer([], cache_time=1, is_personal=True)
            return
        await client.aclose()
        results = [
            InlineQueryResultArticle(
                id=r["id"], title=r["title"], description=r["description"],
                input_message_content=InputTextMessageContent(message_text=r["text"]),
            )
            for r in inline.planner_results(res.get("data", []))
        ]
        await query.answer(results, cache_time=1, is_personal=True)


def _fmt_dt(iso: str) -> str:
    try:
        return iso.replace("T", " ")[:16]
    except (ValueError, TypeError, AttributeError):
        return iso or ""
