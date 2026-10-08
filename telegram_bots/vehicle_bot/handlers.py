"""Доменные команды бота Бортжурнала (ТЗ 7.3): мастера, /quick, /vehicles, /stats, фото.

Бот не знает про ORM — только ходит в API-гейтвей активным сервером (см. ``ConfigStore``).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
from telegram_bots.vehicle_bot.quick import interpret


def _keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def register_handlers(router: Router, store: ConfigStore) -> None:
    async def get_client(message: Message) -> BotAPIClient | None:
        inst = store.active(message.chat.id)
        if not inst:
            return None
        return BotAPIClient(inst.url, inst.token, chat_id=message.chat.id)

    async def get_vehicle(message: Message, client: BotAPIClient) -> str | None:
        vid = store.get_kv(message.chat.id, "vehicle")
        if vid:
            return vid
        try:
            refs = await client.reference("vehicles")
        except BotAPIError:
            return None
        items = refs.get("data", [])
        chosen = next((v for v in items if v.get("is_default")), items[0] if items else None)
        if chosen:
            store.set_kv(message.chat.id, "vehicle", chosen["id"])
            return chosen["id"]
        return None

    # --- регистрации мастеров (generic flow) --------------------------------
    flow.register("create_fuel", "vehicle", [
        Field("odometer", "bot.fuel.odometer", parsers.to_odometer),
        Field("volume_liters", "bot.fuel.volume", parsers.to_liters),
        Field("price_per_liter", "bot.fuel.price", parsers.to_number),
        Field("fuel_date", "bot.fuel.date", parsers.to_date, required=False),
        Field("station_name", "bot.fuel.station", parsers.to_text, required=False),
        Field("full_tank", "bot.fuel.fulltank", parsers.to_bool, required=False),
    ])
    flow.register("create_purchase", "vehicle", [
        Field("title", "bot.purchase.title", parsers.to_text),
        Field("amount", "bot.purchase.amount", parsers.to_money),
        Field("purchase_date", "bot.purchase.date", parsers.to_date, required=False),
        Field("odometer", "bot.purchase.odometer", parsers.to_odometer, required=False),
    ])
    flow.register("create_fine", "vehicle", [
        Field("amount", "bot.fine.amount", parsers.to_money),
        Field("description", "bot.fine.description", parsers.to_text),
        Field("fine_date", "bot.fine.date", parsers.to_date, required=False),
        Field("status", "bot.fine.status", parsers.to_text, required=False),
    ])
    flow.add_collect_handlers(router, get_client, get_vehicle)

    # --- мастера-команды ----------------------------------------------------
    async def _start_master(message, state, action):
        if not store.active(message.chat.id):
            await message.answer(t("bot.no_server"))
            return
        await flow.start(message, state, action)

    @router.message(Command("fuel"))
    async def cmd_fuel(message: Message, state: FSMContext):
        await _start_master(message, state, "create_fuel")

    @router.message(Command("purchase"))
    async def cmd_purchase(message: Message, state: FSMContext):
        await _start_master(message, state, "create_purchase")

    @router.message(Command("fine"))
    async def cmd_fine(message: Message, state: FSMContext):
        await _start_master(message, state, "create_fine")

    # --- сервис с фото (FSM + догруза из Telegram) -------------------------
    class ServiceStates(StatesGroup):
        work = State()
        amount = State()
        station = State()
        date = State()
        odometer = State()
        photos = State()

    @router.message(Command("service"))
    async def cmd_service(message: Message, state: FSMContext):
        if not store.active(message.chat.id):
            await message.answer(t("bot.no_server"))
            return
        await state.set_state(ServiceStates.work)
        await state.update_data(answers={}, photos=[])
        await message.answer(t("bot.service.work"))

    @router.message(ServiceStates.work)
    async def svc_work(message: Message, state: FSMContext):
        data = await state.get_data()
        data["answers"]["work_description"] = message.text.strip()
        await state.set_state(ServiceStates.amount)
        await message.answer(t("bot.service.amount"))

    @router.message(ServiceStates.amount)
    async def svc_amount(message: Message, state: FSMContext):
        try:
            amount = parsers.to_money(message.text)
        except (ValueError, TypeError):
            await message.answer(t("bot.flow.bad_input"))
            return
        data = await state.get_data()
        data["answers"]["amount"] = amount
        await state.set_state(ServiceStates.station)
        await message.answer(t("bot.service.station"))

    @router.message(ServiceStates.station)
    async def svc_station(message: Message, state: FSMContext):
        data = await state.get_data()
        data["answers"]["service_station"] = ("" if message.text.strip() in ("/skip", "-")
                                              else message.text.strip())
        await state.set_state(ServiceStates.date)
        await message.answer(t("bot.service.date"))

    @router.message(ServiceStates.date)
    async def svc_date(message: Message, state: FSMContext):
        data = await state.get_data()
        try:
            data["answers"]["service_date"] = parsers.to_date(message.text)
        except (ValueError, TypeError):
            await message.answer(t("bot.flow.bad_input"))
            return
        await state.set_state(ServiceStates.odometer)
        await message.answer(t("bot.service.odometer"))

    @router.message(ServiceStates.odometer)
    async def svc_odometer(message: Message, state: FSMContext):
        data = await state.get_data()
        if message.text.strip().lower() in ("/skip", "-", "нет"):
            data["answers"]["odometer"] = None
        else:
            try:
                data["answers"]["odometer"] = parsers.to_odometer(message.text)
            except (ValueError, TypeError):
                await message.answer(t("bot.flow.bad_input"))
                return
        await state.set_state(ServiceStates.photos)
        await message.answer(t("bot.service.photos"))

    @router.message(ServiceStates.photos, F.photo)
    async def svc_photo(message: Message, state: FSMContext):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        tg_file = await message.bot.get_file(message.photo[-1].file_id)
        raw = await message.bot.download_file(tg_file.file_path)
        result = await client.upload("photo.jpg", raw.read(), "image/jpeg")
        data = await state.get_data()
        data["photos"].append(result["upload_id"])
        await state.update_data(photos=data["photos"])
        await message.answer(t("bot.service.photo_added"))

    @router.message(ServiceStates.photos, F.text)
    async def svc_done(message: Message, state: FSMContext):
        if message.text.strip().lower() not in ("/done", "готово", "/skip", "-"):
            await message.answer(t("bot.service.photos"))
            return
        data = await state.get_data()
        await state.clear()
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        payload = dict(data["answers"])
        payload["upload_ids"] = data["photos"]
        vid = await get_vehicle(message, client)
        if not vid:
            await message.answer(t("bot.no_vehicle"))
            return
        payload["vehicle_id"] = vid
        try:
            await client.ingest("vehicle", "create_service", payload)
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        await message.answer(t("bot.flow.saved"))

    # --- выбор авто ---------------------------------------------------------
    @router.message(Command("vehicles"))
    async def cmd_vehicles(message: Message):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        try:
            refs = await client.reference("vehicles")
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        items = refs.get("data", [])
        if not items:
            await message.answer(t("bot.vehicles.empty"))
            return
        rows = [[InlineKeyboardButton(
            text=("✅ " if v["id"] == store.get_kv(message.chat.id, "vehicle") else "") + v["name"],
            callback_data=f"veh:set:{v['id']}")] for v in items]
        await message.answer(t("bot.vehicles.title"), reply_markup=_keyboard(rows))

    @router.callback_query(F.data.startswith("veh:set:"))
    async def cb_vehicle(callback: CallbackQuery):
        vid = callback.data.split(":", 2)[2]
        store.set_kv(callback.message.chat.id, "vehicle", vid)
        await callback.answer(t("bot.vehicle.selected"))

    # --- статистика / страховки --------------------------------------------
    @router.message(Command("stats"))
    async def cmd_stats(message: Message):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        try:
            res = await client.ingest("vehicle", "stats")
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        d = res.get("data", {})
        await message.answer(t("bot.stats.text",
                               vehicle=d.get("vehicle") or "—",
                               mileage=d.get("mileage") or 0,
                               expenses=d.get("expenses_month") or "0",
                               fuel=d.get("fuel_month") or "0",
                               fines=d.get("unpaid_fines_count") or 0))

    @router.message(Command("insurance"))
    async def cmd_insurance(message: Message):
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        vid = await get_vehicle(message, client)
        if not vid:
            await message.answer(t("bot.no_vehicle"))
            return
        try:
            res = await client.ingest("vehicle", "list_insurances", {"vehicle_id": vid})
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        items = res.get("data", [])
        lines = [t("bot.insurance.row", type=i["type"], company=i["company"] or "—",
                   end=i["end_date"] or "—") for i in items]
        await message.answer("\n".join(lines) or t("bot.insurance.empty"))

    # --- быстрая запись ----------------------------------------------------
    @router.message(Command("quick"))
    async def cmd_quick(message: Message, command: CommandObject):
        text = (command.args or "").strip()
        if not text:
            await message.answer(t("bot.quick.usage"))
            return
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        stations: list[str] = []
        try:
            refs = await client.reference("fuel_stations")
            stations = [s["name"] for s in refs.get("data", [])]
        except BotAPIError:
            pass
        parsed = interpret(text, stations=stations)
        if parsed is None:
            await message.answer(t("bot.quick.unrecognized"))
            return
        vid = await get_vehicle(message, client)
        if not vid:
            await message.answer(t("bot.no_vehicle"))
            return
        payload = parsed["payload"]
        payload["vehicle_id"] = vid
        try:
            await client.ingest("vehicle", parsed["action"], payload)
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        await message.answer(t("bot.quick.saved", action=parsed["action"]))

    # --- inline-режим (ТЗ 7.5): «поиск:<запрос>» → заправки/покупки -------
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
            res = await client.ingest("vehicle", "search_records", {"query": term, "limit": 10})
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
            for r in inline.vehicle_results(res.get("data", []))
        ]
        await query.answer(results, cache_time=1, is_personal=True)
