"""
Авто-очистка пустых и неактивных комнат.

Каждые ~60 секунд удаляет комнаты, в которых не было действий дольше 30 минут,
а также пустые комнаты сразу. Удаляет их из БД и реестра.
"""

from __future__ import annotations

import asyncio
import logging

from game.registry import all_rooms, unregister
from db.store import store

logger = logging.getLogger(__name__)

INACTIVE_TIMEOUT_SEC = 30 * 60  # 30 минут
CLEANUP_INTERVAL_SEC = 60


async def cleanup_loop() -> None:
    """Фоновая задача очистки."""
    logger.info("Очистка комнат запущена")
    while True:
        try:
            for room in list(all_rooms()):
                if not room.players:
                    await _remove_room(room.code, "пустая комната")
                    continue
                from game.state import Phase
                if room.phase == Phase.FINISHED:
                    await _remove_room(room.code, "игра завершена")
                    continue
            # также подчистим со стороны БД (на случай рестарта без реестра)
            for code in await store.list_inactive_rooms(INACTIVE_TIMEOUT_SEC):
                if code not in {r.code for r in all_rooms()}:
                    await store.delete_room(code)
                    logger.info("Удалена неактивная комната %s из БД", code)
        except asyncio.CancelledError:
            logger.info("Очистка остановлена")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в цикле очистки")
        await asyncio.sleep(CLEANUP_INTERVAL_SEC)


async def _remove_room(code: str, reason: str) -> None:
    try:
        await store.delete_room(code)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось удалить комнату %s из БД", code)
    unregister(code)
    logger.info("Комната %s удалена: %s", code, reason)
