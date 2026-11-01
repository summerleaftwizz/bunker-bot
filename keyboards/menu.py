"""
Клавиатуры главного меню и информационных экранов.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn("🎮 Создать комнату", "menu:create"),
        _btn("🔑 Войти по коду", "menu:join"),
    )
    builder.row(
        _btn("📜 Правила", "menu:rules"),
        _btn("🎮 Мои игры", "menu:my_games"),
    )
    builder.row(
        _btn("📊 Статистика", "menu:stats"),
        _btn("🏆 Топ игроков", "menu:top"),
    )
    builder.row(
        _btn("🧾 История игр", "menu:history"),
        _btn("ℹ️ О боте", "menu:about"),
    )
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    """Одна кнопка «Назад в меню»."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◀️ В меню", "menu:back"))
    return builder.as_markup()


def join_prompt() -> InlineKeyboardMarkup:
    """Экран ввода кода комнаты."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◀️ Назад", "menu:back"))
    return builder.as_markup()
