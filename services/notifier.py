"""
Рассылка сообщений всем игрокам комнаты.

Обрабатывает типовые ошибки Telegram:
- TelegramForbiddenError — игрок заблокировал бота, помечаем отключённым;
- TelegramRetryAfter — ждём указанное время и повторяем;
- TelegramBadRequest «message is not modified» — молча игнорируем.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramAPIError,
)

logger = logging.getLogger(__name__)


async def safe_send(
    bot: Bot,
    user_id: int,
    text: str,
    reply_markup=None,
    disable_notification: bool = True,
) -> bool:
    """
    Отправить сообщение пользователю, не роняя бота при ошибках.

    Возвращает True при успехе, False при фатальной ошибке (например, бот
    заблокирован).
    """
    for attempt in range(3):
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
            return True
        except TelegramForbiddenError:
            logger.warning("Пользователь %s заблокировал бота", user_id)
            return False
        except TelegramRetryAfter as e:
            logger.warning("RetryAfter для %s, ждём %s сек", user_id, e.retry_after)
            await asyncio.sleep(min(e.retry_after, 10))
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return True
            logger.warning("BadRequest при отправке %s: %s", user_id, e)
            return False
        except TelegramAPIError as e:
            logger.warning("API ошибка при отправке %s: %s", user_id, e)
            await asyncio.sleep(1)
    return False


async def safe_edit(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
) -> bool:
    """Безопасно отредактировать сообщение (не падать на «not modified»)."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        logger.warning("BadRequest при edit %s/%s: %s", chat_id, message_id, e)
        return False
    except TelegramForbiddenError:
        return False
    except TelegramAPIError as e:
        logger.warning("API ошибка при edit %s/%s: %s", chat_id, message_id, e)
        return False


async def send_tracked(
    bot: Bot,
    user_id: int,
    text: str,
    reply_markup=None,
) -> Optional[int]:
    """
    Отправить сообщение и вернуть его message_id (или None при ошибке).

    Нужно, чтобы потом обновлять экран через edit_message вместо спама.
    """
    for attempt in range(3):
        try:
            msg = await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                disable_notification=True,
            )
            return msg.message_id
        except TelegramForbiddenError:
            logger.warning("Пользователь %s заблокировал бота", user_id)
            return None
        except TelegramRetryAfter as e:
            logger.warning("RetryAfter для %s, ждём %s сек", user_id, e.retry_after)
            await asyncio.sleep(min(e.retry_after, 10))
        except TelegramBadRequest as e:
            logger.warning("BadRequest при отправке %s: %s", user_id, e)
            return None
        except TelegramAPIError as e:
            logger.warning("API ошибка при отправке %s: %s", user_id, e)
            await asyncio.sleep(1)
    return None


async def broadcast_to_room(
    bot: Bot,
    room,
    text: str,
    reply_markup=None,
    only_alive: bool = False,
    exclude: Optional[set[int]] = None,
) -> dict[int, bool]:
    """
    Разослать сообщение всем игрокам комнаты в их ЛС.

    Возвращает словарь user_id -> успех. Отключившихся игроков помечаем
    disconnected в движке (через колбэк mark_disconnected).
    """
    exclude = exclude or set()
    results: dict[int, bool] = {}
    for player in room.players.values():
        if player.user_id in exclude:
            continue
        if only_alive and not player.alive:
            continue
        ok = await safe_send(bot, player.user_id, text, reply_markup)
        results[player.user_id] = ok
        if not ok:
            player.disconnected = True
    return results
