"""
Клавиатура экрана комнаты (настройки хоста перед стартом).
"""

from __future__ import annotations

from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def room_screen(discussion: int, players: int, special_cards: bool,
                disaster_mode: str, deep_link: str) -> InlineKeyboardMarkup:
    """
    Экран настроек комнаты.

    «Поделиться» — URL-кнопка с deep-link; остальное — настройки и управление.
    """
    builder = InlineKeyboardBuilder()
    share_url = (
        "https://t.me/share/url?url="
        + quote(deep_link, safe="")
        + "&text=" + quote("Играем в Бункер — присоединяйся!")
    )
    builder.row(InlineKeyboardButton(text="🔗 Поделиться", url=share_url))
    builder.row(
        _btn(f"⏱ Обсуждение: {discussion}с", "room:time"),
        _btn(f"👥 Игроки: {players}", "room:players"),
    )
    builder.row(
        _btn(
            "🃏 Особые карты: вкл" if special_cards else "🃏 Особые карты: выкл",
            "room:special",
        ),
        _btn(
            "🌪 Катастрофы: случай" if disaster_mode == "random" else "🌪 Катастрофы: по порядку",
            "room:disaster",
        ),
    )
    builder.row(_btn("▶️ Начать игру", "room:start"))
    builder.row(_btn("🚫 Закрыть комнату", "room:close"))
    builder.row(_btn("◀️ В меню", "menu:back"))
    return builder.as_markup()
