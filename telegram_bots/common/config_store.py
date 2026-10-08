"""Хранилище конфигурации инсталляций бота (ТЗ 7.1/7.2).

Локальная SQLite-база keyed по Telegram ``chat_id``: каждый чат хранит свой набор
серверов ``{id, name, url, token, is_active}`` и выбирает активный. Токен хранится
в открытом виде только на стороне клиента бота (это его «устройство» по ТЗ) и никогда
не логируется.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = os.environ.get("BOT_STATE_DB", "telegram_bots/state.db")


@dataclass
class Installation:
    id: str
    name: str
    url: str
    token: str
    is_active: bool

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "is_active": self.is_active,
            # token не отдаём в словари для показа
        }


class ConfigStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS installations (
                chat_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                token TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (chat_id, key)
            )
            """
        )
        self._conn.commit()

    # -- CRUD ----------------------------------------------------------------

    def add(self, chat_id, iid: str, name: str, url: str, token: str) -> Installation:
        url = url.rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL должен начинаться с http:// или https://")
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM installations WHERE chat_id=?", (str(chat_id),)
            ).fetchone()[0]
            first = count == 0
            self._conn.execute(
                "INSERT OR REPLACE INTO installations (chat_id,id,name,url,token,is_active)"
                " VALUES (?,?,?,?,?,?)",
                (str(chat_id), iid, name, url, token, 1 if first else 0),
            )
            self._conn.commit()
        return Installation(iid, name, url, token, first)

    def list(self, chat_id) -> list[Installation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,name,url,token,is_active FROM installations WHERE chat_id=?"
                " ORDER BY is_active DESC, name",
                (str(chat_id),),
            ).fetchall()
        return [Installation(r[0], r[1], r[2], r[3], bool(r[4])) for r in rows]

    def get(self, chat_id, iid: str) -> Installation | None:
        row = self._conn.execute(
            "SELECT id,name,url,token,is_active FROM installations"
            " WHERE chat_id=? AND id=?",
            (str(chat_id), iid),
        ).fetchone()
        if not row:
            return None
        return Installation(row[0], row[1], row[2], row[3], bool(row[4]))

    def active(self, chat_id) -> Installation | None:
        for inst in self.list(chat_id):
            if inst.is_active:
                return inst
        return None

    def set_active(self, chat_id, iid: str) -> bool:
        if self.get(chat_id, iid) is None:
            return False
        with self._lock:
            self._conn.execute(
                "UPDATE installations SET is_active=0 WHERE chat_id=?", (str(chat_id),)
            )
            self._conn.execute(
                "UPDATE installations SET is_active=1 WHERE chat_id=? AND id=?",
                (str(chat_id), iid),
            )
            self._conn.commit()
        return True

    def remove(self, chat_id, iid: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM installations WHERE chat_id=? AND id=?", (str(chat_id), iid)
            )
            self._conn.commit()
            removed = cur.rowcount > 0
        # Если сняли активный — активируем первый оставшийся
        if removed and not self.active(chat_id):
            rest = self.list(chat_id)
            if rest:
                self.set_active(chat_id, rest[0].id)
        return removed

    def close(self):
        with self._lock:
            self._conn.close()

    # -- Пер-чат состояние (активное авто, скоуп и т.п.) --------------------

    def set_kv(self, chat_id, key: str, value: str | None):
        with self._lock:
            if value is None:
                self._conn.execute(
                    "DELETE FROM chat_state WHERE chat_id=? AND key=?", (str(chat_id), key)
                )
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO chat_state (chat_id,key,value) VALUES (?,?,?)",
                    (str(chat_id), key, value),
                )
            self._conn.commit()

    def get_kv(self, chat_id, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM chat_state WHERE chat_id=? AND key=?", (str(chat_id), key)
        ).fetchone()
        return row[0] if row else None
