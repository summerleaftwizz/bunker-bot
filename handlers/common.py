"""
Общие обработчики: глобальные ошибки и fallback для необработанных сообщений.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import main_menu

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Справка по командам и игре."""
    await message.answer(
        "<b>❓ Помощь по боту «Бункер»</b>\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/cancel — сбросить текущее действие\n\n"
        "<b>Как играть:</b>\n"
        "1️⃣ Создай комнату или войди по коду друга.\n"
        "2️⃣ По очереди раскрывайте карты: раунд 1 — профессия, дальше — "
        "здоровье, хобби, фобии и багаж.\n"
        "3️⃣ Обсуждайте и голосуйте, кто покидает бункер.\n"
        "4️⃣ Побеждают те, кто дожил до мест в убежище.\n\n"
        "<i>Подробнее — кнопка «📜 Правила» в меню.</i>",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Сбросить состояние (например, ввод кода комнаты)."""
    await state.clear()
    await message.answer(
        "↩️ <b>Действие отменено.</b>\n\nВозвращаю в главное меню.",
        reply_markup=main_menu(),
    )


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