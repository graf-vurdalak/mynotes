"""Асинхронный HTTP-клиент к API-гейтвею ``/api/v1/bot/*`` (ТЗ 6.2).

Бот — тонкий клиент: не знает про ORM, только про контракт gateway. Все ответы —
JSON; при 4xx/5xx бросается :class:`BotAPIError` с кодом и человекочитаемым detail.
"""

from __future__ import annotations

import os

import aiohttp


class BotAPIError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class BotAPIClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        session: aiohttp.ClientSession | None = None,
        chat_id: int | str | None = None,
        bot_name: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._session = session
        self._owns_session = session is None
        self.chat_id = chat_id
        self.bot_name = bot_name if bot_name is not None else os.environ.get("BOT_MODULE") or None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    def _headers(self) -> dict:
        headers = {"X-Bot-Token": self.token}
        if self.bot_name:
            headers["X-Bot-Name"] = self.bot_name
        if self.chat_id is not None:
            headers["X-Telegram-Chat-Id"] = str(self.chat_id)
        return headers

    async def _request(self, method: str, path: str, **kwargs):
        session = await self._ensure_session()
        async with session.request(
            method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                detail = ""
                if isinstance(data, dict):
                    detail = data.get("detail") or str(data.get("non_field_errors") or data)
                else:
                    detail = str(data)
                raise BotAPIError(resp.status, detail)
            return data

    async def ping(self) -> dict:
        return await self._request("POST", "/api/v1/bot/ping/")

    async def ingest(self, module: str, action: str, payload: dict | None = None) -> dict:
        return await self._request(
            "POST", "/api/v1/bot/ingest/", json={"module": module, "action": action,
                                                   "payload": payload or {}}
        )

    async def reference(self, ref_type: str) -> dict:
        return await self._request("GET", f"/api/v1/bot/references/{ref_type}/")

    async def upload(self, filename: str, data: bytes, content_type: str) -> dict:
        form = aiohttp.FormData()
        form.add_field("file", data, filename=filename, content_type=content_type)
        return await self._request("POST", "/api/v1/bot/upload/", data=form)

    async def aclose(self):
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
