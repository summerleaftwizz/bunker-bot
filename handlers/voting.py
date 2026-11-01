"""
Обработчики голосования: отдать голос, завершить досрочно, решить ничью хостом.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from db.store import store
from game import engine as eng
from game.registry import get_by_user, lock_for
from keyboards import voting as voting_kb, tiebreak
from services import actions
from services.notifier import safe_send

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "vote:info")
async def cb_vote_info(callback: CallbackQuery) -> None:
    """Показать текущий бюллетень."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await actions.upsert_screen(
        callback.bot, room, callback.from_user.id,
        actions._vote_screen_text(room, callback.from_user.id),
        voting_kb(room, callback.from_user.id),
    )


@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(callback: CallbackQuery) -> None:
    """Отдать голос против игрока."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    try:
        target_id = int(callback.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            eng.vote(room, callback.from_user.id, target_id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)
        await actions.refresh_vote_screens(callback.bot, room)

    await callback.answer("🗳 Голос принят")

    # если проголосовали все живые (кроме отключённых и безмолвных) — подсчёт
    await _maybe_auto_resolve(callback.bot, room)


async def _maybe_auto_resolve(bot, room) -> None:
    """Автоматический подсчёт, когда все, кто может голосовать, проголосовали."""
    alive = [p for p in room.alive_players]
    eligible = [
        p for p in alive
        if not p.disconnected and p.muted_until_round < room.round_no
    ]
    if not eligible:
        return
    if all(p.user_id in room.votes for p in eligible):
        async with lock_for(room.code):
            await actions.resolve_voting_flow(bot, room)


@router.callback_query(F.data == "vote:finish")
async def cb_vote_finish(callback: CallbackQuery) -> None:
    """Хост завершает голосование досрочно."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    if room.host_id != callback.from_user.id:
        await callback.answer("❌ Завершить может только хост.", show_alert=True)
        return

    async with lock_for(room.code):
        await actions.resolve_voting_flow(callback.bot, room)
    await callback.answer("⏹ Голосование завершено")


@router.callback_query(F.data.startswith("tb:"))
async def cb_tiebreak(callback: CallbackQuery) -> None:
    """Хост решает ничью: выбирает, кто выбывает."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    if room.host_id != callback.from_user.id:
        await callback.answer("❌ Решение принимает только хост.", show_alert=True)
        return

    try:
        target_id = int(callback.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            eng.host_resolve_tie(room, callback.from_user.id, target_id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)
        await actions.resolve_voting_flow(callback.bot, room)
    await callback.answer("🔨 Решение принято")


@router.callback_query(F.data == "res:next")
async def cb_result_next(callback: CallbackQuery) -> None:
    """Хост подтвердил переход к следующему раунду после результата."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    if room.host_id != callback.from_user.id:
        await callback.answer("❌ Продолжить может только хост.", show_alert=True)
        return

    from game.state import Phase

    if room.phase != Phase.RESULT:
        await callback.answer()
        return

    async with lock_for(room.code):
        finished = eng.continue_after_result(room)
        await store.save_room(room)
        if finished:
            await actions.finish_game(callback.bot, room)
        else:
            await actions.begin_reveal_round(callback.bot, room)
    await callback.answer("▶️ Следующий раунд")