"""
Клавиатуры лобби.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def lobby(room, viewer_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура лобби.

    Хост видит «Старт», «Настройки» и кнопки кика; остальные — только выход.
    """
    builder = InlineKeyboardBuilder()
    viewer = room.players.get(viewer_id)
    is_host = bool(viewer and viewer.is_host)

    if is_host:
        builder.row(
            _btn("▶️ Старт", "lobby:start"),
            _btn("⚙️ Настройки", "lobby:settings"),
        )
        for p in sorted(room.players.values(), key=lambda x: x.join_index):
            if p.user_id == viewer_id:
                continue
            builder.row(_btn(f"🚫 Кикнуть {p.full_name}", f"lobby:kickq:{p.user_id}"))
    else:
        builder.row(_btn("🔔 Позвать хоста", "lobby:ping_host"))

    builder.row(_btn("🔗 Пригласить друга", "lobby:invite"))
    builder.row(_btn("🚪 Выйти", "lobby:leave"))
    return builder.as_markup()


def kick_confirm(target_id: int, target_name: str) -> InlineKeyboardMarkup:
    """Подтверждение кика: случайное нажатие не выгонит игрока."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(f"✅ Да, кикнуть {target_name}", f"lobby:kick:{target_id}"),
    )
    builder.row(_btn("❌ Отмена", "lobby:show"))
    return builder.as_markup()


def lobby_back() -> InlineKeyboardMarkup:
    """Возврат из настроек в лобби."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◀️ В лобби", "lobby:show"))
    return builder.as_markup()
