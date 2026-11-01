"""
Игровые клавиатуры: карточка игрока, раскрытие, особые карты, голосование.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from game.state import CARD_ICONS, CARD_LABELS, Phase, theme_for_round, SPECIAL
from data.special_cards import SPECIAL_CARDS_MAP


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def card_screen(room, viewer_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура личной карточки игрока.

    Кнопка раскрытия зависит от фазы и темы раунда; особая карта показывается,
    если она есть и ещё не использована.
    """
    builder = InlineKeyboardBuilder()
    player = room.players.get(viewer_id)
    if player is None:
        return builder.as_markup()

    if room.phase == Phase.REVEAL and player.alive:
        theme = theme_for_round(room.round_no)
        if theme is not None:
            if theme not in player.revealed:
                builder.row(_btn(
                    f"{CARD_ICONS.get(theme, '•')} Раскрыть: {CARD_LABELS.get(theme, theme)}",
                    f"reveal:{theme}",
                ))
        else:
            for attr in player.hidden_cards():
                if attr == SPECIAL:
                    continue
                builder.row(_btn(
                    f"{CARD_ICONS.get(attr, '•')} Раскрыть: {CARD_LABELS.get(attr, attr)}",
                    f"reveal:{attr}",
                ))

    # особая карта
    if player.alive and player.special_key and not player.special_used and \
            room.phase not in (Phase.LOBBY, Phase.FINISHED):
        title = SPECIAL_CARDS_MAP.get(player.special_key, ("Особая карта", "", False))[0]
        builder.row(_btn(f"🃏 Использовать: {title}", "sp:open"))

    if room.phase == Phase.VOTING and player.alive:
        builder.row(_btn("🗳 Голосовать", "vote:info"))

    builder.row(
        _btn("📜 Катастрофа", "game:mission"),
        _btn("🏚 Бункер", "game:bunker"),
    )
    builder.row(_btn("🔄 Обновить", "game:cards"))
    return builder.as_markup()


def special_targets(room, viewer_id: int) -> InlineKeyboardMarkup:
    """Выбор цели для особой карты, требующей другого игрока."""
    builder = InlineKeyboardBuilder()
    for p in sorted(room.players.values(), key=lambda x: x.join_index):
        if p.user_id == viewer_id or not p.alive:
            continue
        builder.row(_btn(f"🎯 {p.full_name}", f"sp:target:{p.user_id}"))
    builder.row(_btn("◀️ Отмена", "game:cards"))
    return builder.as_markup()


def special_confirm(room, viewer_id: int) -> InlineKeyboardMarkup:
    """Подтверждение особой карты без цели."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("✅ Применить", "sp:apply"))
    builder.row(_btn("◀️ Отмена", "game:cards"))
    return builder.as_markup()


def voting(room, viewer_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура голосования: все живые игроки, кроме себя.

    При переголосовании список ограничен лидерами.
    """
    builder = InlineKeyboardBuilder()
    allowed = room.restricted_targets
    for p in sorted(room.players.values(), key=lambda x: x.join_index):
        if not p.alive or p.user_id == viewer_id:
            continue
        if allowed is not None and p.user_id not in allowed:
            continue
        builder.row(_btn(f"❌ {p.full_name}", f"vote:{p.user_id}"))
    if room.host_id == viewer_id:
        builder.row(_btn("⏹ Завершить голосование", "vote:finish"))
    builder.row(_btn("◀️ Мои карты", "game:cards"))
    return builder.as_markup()


def tiebreak(room) -> InlineKeyboardMarkup:
    """Решение хоста при повторной ничьей."""
    builder = InlineKeyboardBuilder()
    for uid in room.tie_leaders:
        player = room.players.get(uid)
        if player is None:
            continue
        builder.row(_btn(f"🔨 Выгнать: {player.full_name}", f"tb:{uid}"))
    return builder.as_markup()


def after_result(viewer_id: int, is_host: bool, finished: bool) -> InlineKeyboardMarkup:
    """Кнопки после результата голосования."""
    builder = InlineKeyboardBuilder()
    if finished:
        builder.row(_btn("🃏 Мои карты", "game:cards"))
        builder.row(_btn("🏠 В меню", "menu:back"))
        return builder.as_markup()

    if is_host:
        builder.row(_btn("▶️ Следующий раунд", "res:next"))
    builder.row(_btn("🃏 Мои карты", "game:cards"))
    return builder.as_markup()
