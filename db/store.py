"""
Асинхронное хранилище состояния на SQLite (aiosqlite).

Схема простая и надёжная: комнаты хранятся как JSON-снимок состояния движка
(room.state_json), плюс отдельная таблица участников с уникальным индексом
по user_id — это жёстко гарантирует правило «один игрок — одна активная комната».
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

import aiosqlite

from config import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    code TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    host_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_activity REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS room_players (
    code TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    username TEXT,
    is_host INTEGER NOT NULL DEFAULT 0,
    joined_at REAL NOT NULL,
    PRIMARY KEY (code, user_id)
);

-- Один пользователь не может состоять более чем в одной активной комнате.
CREATE UNIQUE INDEX IF NOT EXISTS idx_room_players_user ON room_players(user_id);

CREATE TABLE IF NOT EXISTS user_stats (
    user_id INTEGER PRIMARY KEY,
    games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    last_game_at REAL
);

CREATE TABLE IF NOT EXISTS games_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    finished_at REAL NOT NULL,
    disaster TEXT,
    survivors_json TEXT,
    players_json TEXT
);
"""


class Store:
    """
    Обёртка над одним подключением aiosqlite.

    Все операции сериализованы одним asyncio.Lock — это исключает гонки
    записи при высокой нагрузке.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        # aiosqlite ожидает обычный путь к файлу, а не URL
        raw = db_path or config.DB_PATH
        if raw.startswith("sqlite+aiosqlite:///"):
            raw = raw[len("sqlite+aiosqlite:///"):]
        self._path = raw or "bunker.db"
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self, db_path: str | None = None) -> None:
        """Открыть соединение (и создать схему) с заданным или стандартным путём."""
        if db_path is not None:
            raw = db_path
            if raw.startswith("sqlite+aiosqlite:///"):
                raw = raw[len("sqlite+aiosqlite:///"):]
            self._path = raw or "bunker.db"
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Store не подключён. Вызовите await store.connect().")
        return self._conn

    # ------------------------------------------------------------------
    # Комнаты
    # ------------------------------------------------------------------
    async def save_room(self, room) -> None:
        """Сохранить снимок комнаты и список её участников."""
        data = room.to_dict()
        now = time.time()
        await self.conn.execute(
            """
            INSERT INTO rooms (code, state_json, host_id, phase, created_at, updated_at, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                state_json=excluded.state_json,
                host_id=excluded.host_id,
                phase=excluded.phase,
                updated_at=excluded.updated_at,
                last_activity=excluded.last_activity
            """,
            (
                room.code,
                json.dumps(data, ensure_ascii=False),
                room.host_id,
                room.phase.value,
                room.created_at,
                room.updated_at,
                room.updated_at,
            ),
        )
        # перезаписываем участников комнаты
        await self.conn.execute("DELETE FROM room_players WHERE code = ?", (room.code,))
        for p in room.players.values():
            await self.conn.execute(
                """
                INSERT INTO room_players (code, user_id, full_name, username, is_host, joined_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    room.code,
                    p.user_id,
                    p.full_name,
                    p.username,
                    int(p.is_host),
                    room.created_at,
                ),
            )
        await self.conn.commit()

    async def delete_room(self, code: str) -> None:
        """Удалить комнату и её участников."""
        await self.conn.execute("DELETE FROM rooms WHERE code = ?", (code,))
        await self.conn.execute("DELETE FROM room_players WHERE code = ?", (code,))
        await self.conn.commit()

    async def clear_players(self, code: str) -> None:
        """
        Снять участников комнаты (игра завершена).

        Комната остаётся в БД до авто-очистки, но игроки снова могут
        вступать в другие комнаты.
        """
        await self.conn.execute("DELETE FROM room_players WHERE code = ?", (code,))
        await self.conn.commit()

    async def touch_room(self, code: str) -> None:
        """Обновить last_activity (защита от авто-очистки активной комнаты)."""
        await self.conn.execute(
            "UPDATE rooms SET last_activity = ? WHERE code = ?",
            (time.time(), code),
        )
        await self.conn.commit()

    async def load_active_rooms(self):
        """Загрузить все комнаты из БД (для восстановления после рестарта)."""
        from game.engine import GameRoom

        cursor = await self.conn.execute("SELECT state_json FROM rooms")
        rows = await cursor.fetchall()
        rooms = []
        for row in rows:
            try:
                data = json.loads(row["state_json"])
                rooms.append(GameRoom.from_dict(data))
            except Exception:  # noqa: BLE001 - битый снимок не должен ронять бот
                logger.exception("Не удалось восстановить комнату из БД")
        return rooms

    async def get_active_room_codes(self) -> list[str]:
        cursor = await self.conn.execute("SELECT code FROM rooms")
        rows = await cursor.fetchall()
        return [r["code"] for r in rows]

    async def list_inactive_rooms(self, timeout_sec: float) -> list[str]:
        """Коды комнат, неактивных дольше timeout_sec."""
        cutoff = time.time() - timeout_sec
        cursor = await self.conn.execute(
            "SELECT code FROM rooms WHERE last_activity < ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [r["code"] for r in rows]

    # ------------------------------------------------------------------
    # Участники / единственная активная комната
    # ------------------------------------------------------------------
    async def get_user_room_code(self, user_id: int) -> Optional[str]:
        cursor = await self.conn.execute(
            "SELECT code FROM room_players WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["code"] if row else None

    async def get_room_codes_of_user(self, user_id: int) -> list[str]:
        cursor = await self.conn.execute(
            "SELECT code FROM room_players WHERE user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [r["code"] for r in rows]

    async def get_room_by_code(self, code: str):
        """Загрузить одну комнату по коду."""
        from game.engine import GameRoom

        cursor = await self.conn.execute(
            "SELECT state_json FROM rooms WHERE code = ?",
            (code,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            return GameRoom.from_dict(json.loads(row["state_json"]))
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось прочитать комнату %s", code)
            return None

    # ------------------------------------------------------------------
    # Статистика и лог игр
    # ------------------------------------------------------------------
    async def bump_stats(self, user_id: int, won: bool) -> None:
        await self.conn.execute(
            """
            INSERT INTO user_stats (user_id, games, wins, last_game_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                games = games + 1,
                wins = wins + excluded.wins,
                last_game_at = excluded.last_game_at
            """,
            (user_id, int(won), time.time()),
        )
        await self.conn.commit()

    async def get_user_stats(self, user_id: int) -> dict[str, int]:
        cursor = await self.conn.execute(
            "SELECT games, wins FROM user_stats WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"games": 0, "wins": 0}
        return {"games": row["games"], "wins": row["wins"]}

    async def log_game(self, code: str, disaster: str, survivors: list[int],
                       players: list[dict[str, object]]) -> None:
        await self.conn.execute(
            """
            INSERT INTO games_log (code, finished_at, disaster, survivors_json, players_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                code,
                time.time(),
                disaster,
                json.dumps(survivors, ensure_ascii=False),
                json.dumps(players, ensure_ascii=False),
            ),
        )
        await self.conn.commit()

    async def totals(self) -> dict[str, int]:
        """Общая статистика для /stats."""
        rooms_cursor = await self.conn.execute("SELECT COUNT(*) AS c FROM rooms")
        rooms = (await rooms_cursor.fetchone())["c"]

        players_cursor = await self.conn.execute("SELECT COUNT(*) AS c FROM room_players")
        active_players = (await players_cursor.fetchone())["c"]

        games_cursor = await self.conn.execute("SELECT COUNT(*) AS c FROM games_log")
        games = (await games_cursor.fetchone())["c"]

        stats_cursor = await self.conn.execute("SELECT COUNT(*) AS c FROM user_stats")
        users = (await stats_cursor.fetchone())["c"]

        return {
            "rooms": rooms,
            "active_players": active_players,
            "games": games,
            "users": users,
        }


# Глобальный экземпляр хранилища
store = Store()


def new_id() -> str:
    """Сгенерировать UUID."""
    return str(uuid.uuid4())
