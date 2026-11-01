"""
Админ-функции: /stats, /broadcast, /close_room — только для ADMIN_IDS.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery

from config import config
from db.store import store
from game.registry import all_rooms, unregister
from services.notifier import safe_send

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Сводная статистика бота."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Доступно только администраторам.")
        return

    totals = await store.totals()
    await message.answer(
        "<b>📊 Статистика бота</b>\n\n"
        f"🛋 Активных комнат: <b>{totals['rooms']}</b>\n"
        f"👥 Игроков в комнатах: <b>{totals['active_players']}</b>\n"
        f"🎮 Завершено игр: <b>{totals['games']}</b>\n"
        f"🙋 Уникальных игроков: <b>{totals['users']}</b>"
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject) -> None:
    """Рассылка всем пользователям (по комнатам)."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Доступно только администраторам.")
        return

    text = (command.args or "").strip()
    if not text:
        await message.answer("📣 Использование: /broadcast <текст>")
        return

    seen: set[int] = set()
    delivered = 0
    for room in all_rooms():
        for player in room.players.values():
            if player.user_id in seen:
                continue
            seen.add(player.user_id)
            if await safe_send(message.bot, player.user_id, f"📣 <b>Рассылка:</b>\n\n{text}"):
                delivered += 1

    await message.answer(f"📣 Отправлено <b>{delivered}</b> игрокам.")


@router.message(Command("close_room"))
async def cmd_close_room(message: Message, command: CommandObject) -> None:
    """Принудительно закрыть комнату по коду."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Доступно только администраторам.")
        return

    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("🚫 Использование: /close_room <код>")
        return

    room = None
    for r in all_rooms():
        if r.code == code:
            room = r
            break
    if room is None:
        await message.answer(f"❌ Комната <code>{code}</code> не найдена.")
        return

    for uid in list(room.players.keys()):
        await safe_send(message.bot, uid,
                        f"🚫 <b>Комната <code>{code}</code> закрыта администратором.</b>")
    await store.delete_room(code)
    unregister(code)
    await message.answer(f"✅ Комната <code>{code}</code> закрыта.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Справка по командам."""
    text = (
        "<b>🆘 Справка</b>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
    )
    if _is_admin(message.from_user.id):
        text += "\n<b>Админ:</b>\n/stats — статистика\n/broadcast <текст> — рассылка\n/close_room <код> — закрыть комнату\n"
    await message.answer(text)