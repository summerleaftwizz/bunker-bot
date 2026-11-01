"""
Middleware-компоненты для aiogram.

- ThrottlingMiddleware: антиспам для команд и callback-ов.
- DbmwMiddleware: подключение сессии БД к контексту события.
"""

from __future__ import annotations

import time
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """
    Простой антиспам: раз в RATE_LIMIT секунд один пользователь может
    вызвать хендлер на одну команду/callback. Избыточные вызовы игнорируются
    с ответом в виде alert.
    """

    RATE_LIMIT = 1.5  # секунды между действиями одного пользователя
    _last_event: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user_id = getattr(event, "from_user", None)
        if user_id is None:
            # Не сообщение и не callback — пропускаем
            return await handler(event, data)

        uid = user_id.id
        if isinstance(event, (Message, CallbackQuery)):
            now = time.monotonic()
            last = self._last_event.get(uid, 0.0)
            if now - last < self.RATE_LIMIT:
                if isinstance(event, CallbackQuery):
                    await event.answer("⚡️ Не так быстро!", show_alert=False)
                return None
            self._last_event[uid] = now

        return await handler(event, data)


class DbMiddleware(BaseMiddleware):
    """
    Добавляет активную сессию БД (db.store.store) в контекст события.
    
    Хранилище использует глобальное соединение, поэтому здесь просто
    гарантируем, что оно инициализировано.
    """

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        from db.store import store
        data["db"] = store
        return await handler(event, data)
