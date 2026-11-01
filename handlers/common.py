"""
Общие обработчики: глобальные ошибки и fallback для необработанных сообщений.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message

from keyboards import main_menu

logger = logging.getLogger(__name__)
router = Router()


@router.errors()
async def global_error_handler(event, exception: Exception) -> bool:
    """
    Глобальный обработчик ошибок.

    Логируем исключение и вежливо отвечаем пользователю. Возвращаем True —
    ошибка «съедена», бот продолжает работать.
    """
    logger.exception("Ошибка в хендлере: %s", exception)
    try:
        message = getattr(event, "message", None)
        if message is not None:
            await message.answer(
                "⚠️ <b>Что-то пошло не так.</b>\n\n"
                "Попробуй ещё раз. Если повторяется — напиши в поддержку.",
                reply_markup=main_menu(),
            )
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось отправить сообщение об ошибке")
    return True


@router.message(F.text)
async def fallback_message(message: Message) -> None:
    """Любое необработанное текстовое сообщение."""
    await message.answer(
        "🤖 Я понимаю только кнопки и команды.\n\n"
        "Нажми /start, чтобы открыть главное меню.",
        reply_markup=main_menu(),
    )


@router.callback_query()
async def fallback_callback(callback) -> None:
    """Неопознанный callback — тихо игнорируем, чтобы не пугать пользователя."""
    try:
        await callback.answer()
    except Exception:  # noqa: BLE001
        pass