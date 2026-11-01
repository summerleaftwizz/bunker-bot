"""
Реестр активных комнат в памяти + блокировки на комнату.

Именно здесь живут «живые» комнаты между апдейтами. После рестарта бота
комнаты восстанавливаются из БД (services.recovery).

Каждая комната защищена своим asyncio.Lock — это исключает гонки между
параллельными callback-ами игроков одной комнаты.
"""

from __future__ import annotations

import asyncio
import random
import string
from typing import Optional

from game.engine import GameRoom
from game import engine as engine_mod

# Допустимые символы кода комнаты: без похожих (O/0, I/1, l)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

_rooms: dict[str, GameRoom] = {}
_locks: dict[str, asyncio.Lock] = {}


def generate_code(length: int = 5) -> str:
    """Сгенерировать уникальный код комнаты из безопасного алфавита."""
    while True:
        code = "".join(random.choice(CODE_ALPHABET) for _ in range(length))
        if code not in _rooms:
            return code


def get(code: str) -> Optional[GameRoom]:
    """Получить комнату по коду или None."""
    return _rooms.get(code)


def get_by_user(user_id: int) -> Optional[GameRoom]:
    """Найти комнату, в которой состоит игрок."""
    for room in _rooms.values():
        if user_id in room.players:
            return room
    return None


def lock_for(code: str) -> asyncio.Lock:
    """Вернуть (создав при необходимости) блокировку комнаты."""
    lock = _locks.get(code)
    if lock is None:
        lock = asyncio.Lock()
        _locks[code] = lock
    return lock


def register(room: GameRoom) -> None:
    """Добавить комнату в реестр."""
    _rooms[room.code] = room
    _locks.setdefault(room.code, asyncio.Lock())


def unregister(code: str) -> None:
    """Удалить комнату из реестра (комната закрыта/завершена)."""
    _rooms.pop(code, None)
    _locks.pop(code, None)


def all_rooms() -> list[GameRoom]:
    """Все активные комнаты."""
    return list(_rooms.values())


def room_count() -> int:
    """Число активных комнат."""
    return len(_rooms)
