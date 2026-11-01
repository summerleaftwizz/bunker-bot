"""
Восстановление активных комнат после рестарта бота.

При старте загружает комнаты из БД в реестр. Фаза DISCUSSION продолжает
свой таймер (deadline хранится абсолютным временем в снимке).
"""

from __future__ import annotations

import logging

from db.store import store
from game import registry

logger = logging.getLogger(__name__)


async def restore_rooms() -> int:
    """Загрузить все активные комнаты из БД. Возвращает их число."""
    rooms = await store.load_active_rooms()
    restored = 0
    for room in rooms:
        registry.register(room)
        restored += 1
        logger.info(
            "Восстановлена комната %s (фаза %s, игроков %d)",
            room.code,
            room.phase.value,
            len(room.players),
        )
    return restored
