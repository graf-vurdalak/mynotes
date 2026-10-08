"""Универсальный пошаговый мастер (FSM) для ботов (ТЗ 7.3/7.4).

В FSM в памяти хранятся только JSON-safe данные (action, step, answers); определения
полей берутся из реестра ``FLOWS`` по ``action``. В конце мастер собирает payload
(с активным ``vehicle_id`` для Бортжурнала) и вызывает ``/api/v1/bot/ingest``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .api_client import BotAPIError
from .texts import t


@dataclass
class Field:
    key: str
    prompt_key: str
    parse: Callable[[str], object]
    required: bool = True


class CollectStates(StatesGroup):
    waiting = State()


# action -> (module, [Field])
FLOWS: dict[str, tuple[str, list[Field]]] = {}

# action -> callable(answers) -> dict payload (необязательная постобработка)
BUILDERS: dict[str, Callable[[dict], dict]] = {}


def register(action: str, module: str, fields: list[Field], builder=None):
    FLOWS[action] = (module, fields)
    if builder:
        BUILDERS[action] = builder


async def start(message: Message, state: FSMContext, action: str):
    _, fields = FLOWS[action]
    await state.set_state(CollectStates.waiting)
    await state.update_data(action=action, step=0, answers={})
    await message.answer(t(fields[0].prompt_key))


def add_collect_handlers(router: Router, get_client, get_vehicle):
    """Регистрирует обработчик текстового ввода мастера.

    ``get_client(message)`` → BotAPIClient | None;
    ``get_vehicle(message, client)`` → vehicle_id | None.
    """

    @router.message(CollectStates.waiting)
    async def _collect(message: Message, state: FSMContext):
        data = await state.get_data()
        action = data.get("action")
        if action not in FLOWS:  # мастер сброшен/неизвестен
            await state.clear()
            await message.answer(t("bot.flow.expired"))
            return
        module, fields = FLOWS[action]
        step = data["step"]
        answers = data["answers"]
        f = fields[step]
        text = (message.text or "").strip()

        if text.lower() in ("/skip", "skip", "-") and not f.required:
            answers[f.key] = None
        else:
            try:
                answers[f.key] = f.parse(text)
            except (ValueError, TypeError):
                await message.answer(t("bot.flow.bad_input"))
                return

        nxt = step + 1
        await state.update_data(answers=answers, step=nxt)
        if nxt < len(fields):
            await message.answer(t(fields[nxt].prompt_key))
            return

        await state.clear()
        client = await get_client(message)
        if client is None:
            await message.answer(t("bot.no_server"))
            return
        payload = BUILDERS[action](answers) if action in BUILDERS else dict(answers)
        if module == "vehicle":
            vehicle_id = await get_vehicle(message, client)
            if not vehicle_id:
                await message.answer(t("bot.no_vehicle"))
                return
            payload["vehicle_id"] = vehicle_id
        try:
            await client.ingest(module, action, payload)
        except BotAPIError as exc:
            await message.answer(t("bot.flow.error", detail=exc.detail))
            return
        await message.answer(t("bot.flow.saved"))
