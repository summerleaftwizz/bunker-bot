"""
Фоновая задача таймеров обсуждения.

Каждые TICK_SECONDS проверяет комнаты в фазе DISCUSSION:
- пока таймер идёт — обновляет счётчик у игроков (не чаще раза в 5 секунд,
  редактируя уже существующее сообщение, а не отправляя новые);
- когда время вышло — открывает голосование.
"""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot

from db.store import store
from game.registry import all_rooms, lock_for
from game.state import Phase
from keyboards import card_screen
from services import actions

logger = logging.getLogger(__name__)

TICK_SECONDS = 2.0
COUNTDOWN_UPDATE_INTERVAL = 5.0

# время последнего обновления счётчика: code -> monotonic
_last_countdown_sent: dict[str, float] = {}


def _countdown_text(room) -> str:
    """Оставшееся время обсуждения в формате MM:SS."""
    if room.discussion_deadline is None:
        return "—"
    left = max(0, int(room.discussion_deadline - time.time()))
    return f"{left // 60:02d}:{left % 60:02d}"


def _discussion_text(room) -> str:
    """Текст экрана обсуждения с обратным отсчётом."""
    return (
        f"🗣 <b>Обсуждение</b> · раунд {room.round_no}\n\n"
        f"⏳ Осталось: <b>{_countdown_text(room)}</b>\n\n"
        "<i>Свои карты можно открыть кнопкой «Обновить».</i>"
    )


async def timers_loop(bot: Bot) -> None:
    """Бесконечный цикл таймеров обсуждения."""
    logger.info("Таймеры обсуждения запущены")
    while True:
        try:
            now = time.time()
            for room in all_rooms():
                if room.phase != Phase.DISCUSSION or room.discussion_deadline is None:
                    _last_countdown_sent.pop(room.code, None)
                    continue

                if room.discussion_deadline <= now:
                    # время вышло — открываем голосование
                    async with lock_for(room.code):
                        if (room.phase == Phase.DISCUSSION
                                and room.discussion_deadline is not None
                                and room.discussion_deadline <= time.time()):
                            await actions.open_voting(bot, room)
                            _last_countdown_sent.pop(room.code, None)
                    continue

                # обновляем отсчёт не чаще раза в 5 секунд
                last = _last_countdown_sent.get(room.code, 0.0)
                if now - last >= COUNTDOWN_UPDATE_INTERVAL:
                    _last_countdown_sent[room.code] = now
                    for player in room.alive_players:
                        await actions.upsert_screen(
                            bot,
                            room,
                            player.user_id,
                            _discussion_text(room),
                            card_screen(room, player.user_id),
                        )
                    await store.save_room(room)
        except asyncio.CancelledError:
            logger.info("Таймеры обсуждения остановлены")
            raise
        except Exception:  # noqa: BLE001 - цикл не должен умирать
            logger.exception("Ошибка в цикле таймеров")
        await asyncio.sleep(TICK_SECONDS)
