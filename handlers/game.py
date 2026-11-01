"""
Игровые обработчики: личная карточка, раскрытие карт, особые карты.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db.store import store
from gamedata.special_cards import SPECIAL_CARDS_MAP
from game import engine as eng
from game.registry import get_by_user, lock_for
from keyboards import card_screen, special_targets, special_confirm
from services import actions
from services.actions import (
    upsert_screen,
    card_screen_text,
    mission_text,
    after_reveal,
)
from services.notifier import broadcast_to_room, safe_send

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Личные экраны
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "game:cards")
async def cb_card_screen(callback: CallbackQuery) -> None:
    """Показать/обновить свою карточку."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        card_screen_text(room, callback.from_user.id),
        card_screen(room, callback.from_user.id),
    )


@router.callback_query(F.data == "game:my_cards")
async def cb_my_cards(callback: CallbackQuery) -> None:
    """Псевдоним game:cards."""
    await cb_card_screen(callback)


@router.callback_query(F.data == "game:mission")
async def cb_mission(callback: CallbackQuery) -> None:
    """Показать катастрофу и бункер."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        mission_text(room),
        card_screen(room, callback.from_user.id),
    )


@router.callback_query(F.data == "game:bunker")
async def cb_bunker(callback: CallbackQuery) -> None:
    """Показать только бункер."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        room.bunker or "🏚 <i>Бункер ещё не определён.</i>",
        card_screen(room, callback.from_user.id),
    )


@router.callback_query(F.data == "game:menu")
async def cb_game_menu(callback: CallbackQuery) -> None:
    """Мини-меню во время игры."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🃏 Мои карты", callback_data="game:cards"),
            InlineKeyboardButton(text="📜 Катастрофа", callback_data="game:mission"),
        ],
        [InlineKeyboardButton(text="🏚 Бункер", callback_data="game:bunker")],
    ])
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        "🏠 <b>Меню игры</b>\n\n<i>Выбери, что показать.</i>",
        kb,
    )


# ---------------------------------------------------------------------------
# Кто в игре (с пагинацией)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "game:who")
async def cb_who_is_here(callback: CallbackQuery) -> None:
    """Показать список игроков: кто жив, кто выбыл."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    text, pages = actions.players_list_text(room, page=0)
    await upsert_screen(
        callback.bot, room, callback.from_user.id, text,
        actions.players_list_keyboard(0, pages),
    )


@router.callback_query(F.data.startswith("who:page:"))
async def cb_who_page(callback: CallbackQuery) -> None:
    """Страница списка игроков."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        page = 0
    await callback.answer()
    text, pages = actions.players_list_text(room, page=page)
    await upsert_screen(
        callback.bot, room, callback.from_user.id, text,
        actions.players_list_keyboard(page, pages),
    )


# ---------------------------------------------------------------------------
# Карты картинкой (Pillow) и пауза
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "game:img")
async def cb_card_image(callback: CallbackQuery) -> None:
    """Отправить карточку игрока PNG-картинкой (или текстом, если Pillow нет)."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()

    player = room.players.get(callback.from_user.id)
    if player is None:
        return

    from services.cards_image import render_player_card

    png = render_player_card(player, room_code=room.code)
    if png is None:
        await upsert_screen(
            callback.bot, room, callback.from_user.id,
            card_screen_text(room, callback.from_user.id),
            card_screen(room, callback.from_user.id),
        )
        return

    from aiogram.types import BufferedInputFile

    photo = BufferedInputFile(png, filename=f"card_{room.code}.png")
    try:
        await callback.bot.send_photo(
            callback.from_user.id, photo,
            caption=f"🃏 Досье игрока <b>{actions.esc(player.full_name)}</b> "
                    f"· комната <code>{room.code}</code>",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось отправить PNG-карточку")
        await upsert_screen(
            callback.bot, room, callback.from_user.id,
            card_screen_text(room, callback.from_user.id),
            card_screen(room, callback.from_user.id),
        )


@router.callback_query(F.data == "game:pause")
async def cb_pause_toggle(callback: CallbackQuery) -> None:
    """Хост ставит игру на паузу или снимает её."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    if room.host_id != callback.from_user.id:
        await callback.answer("❌ Пауза доступна только хосту.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            await actions.set_paused(callback.bot, room, callback.from_user.id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await upsert_screen(
            callback.bot, room, callback.from_user.id,
            card_screen_text(room, callback.from_user.id),
            card_screen(room, callback.from_user.id),
        )

    await callback.answer(
        "▶️ Игра продолжается" if not room.paused else "⏸ Пауза"
    )


# ---------------------------------------------------------------------------
# Раскрытие карты
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "reveal:done")
async def cb_reveal_done(callback: CallbackQuery) -> None:
    """
    Кнопка «Готов к обсуждению».

    Если все живые уже раскрылись — начинаем обсуждение; иначе просим подождать.
    """
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    from services.actions import begin_discussion

    async with lock_for(room.code):
        if eng.all_revealed_for_round(room):
            await callback.answer("✅ Все готовы!")
            await begin_discussion(callback.bot, room)
            return
    await callback.answer("⏳ Ещё не все раскрыли карты.", show_alert=False)


@router.callback_query(F.data.startswith("reveal:"))
async def cb_reveal(callback: CallbackQuery) -> None:
    """Раскрыть карту игрока (профессия, здоровье и т.д.)."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    attr = callback.data.split(":", 1)[1]

    async with lock_for(room.code):
        try:
            eng.reveal_card(room, callback.from_user.id, attr)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return

        player = room.players[callback.from_user.id]
        await upsert_screen(
            callback.bot,
            room,
            callback.from_user.id,
            card_screen_text(room, callback.from_user.id),
            card_screen(room, callback.from_user.id),
        )
        await store.save_room(room)

        await callback.answer("🔓 Карта раскрыта")

        await after_reveal(callback.bot, room, player, attr)


# ---------------------------------------------------------------------------
# Особые карты
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "sp:open")
async def cb_special_menu(callback: CallbackQuery) -> None:
    """Экран применения особой карты."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()

    player = room.players.get(callback.from_user.id)
    if player is None or not player.special_key or player.special_used:
        await safe_send(callback.bot, callback.from_user.id, "❌ Особая карта недоступна.")
        return

    key = player.special_key
    title, description, needs_target = SPECIAL_CARDS_MAP.get(key, ("?", "", False))

    if needs_target:
        kb = special_targets(room, callback.from_user.id)
        text = (
            f"🃏 <b>Особая карта: {title}</b>\n\n"
            f"<blockquote>{description}</blockquote>\n\n"
            "<i>Выбери цель:</i>"
        )
    else:
        kb = special_confirm(room, callback.from_user.id)
        text = (
            f"🃏 <b>Особая карта: {title}</b>\n\n"
            f"<blockquote>{description}</blockquote>\n\n"
            "<i>Применить карту?</i>"
        )

    await upsert_screen(callback.bot, room, callback.from_user.id, text, kb)


@router.callback_query(F.data.startswith("sp:target:"))
async def cb_special_target(callback: CallbackQuery) -> None:
    """Применить особую карту к выбранной цели."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    try:
        target_id = int(callback.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Некорректная цель.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            result = eng.use_special_card(room, callback.from_user.id, target_id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)

    await callback.answer("🃏 Карта применена")
    await safe_send(callback.bot, callback.from_user.id, result)
    await broadcast_to_room(
        callback.bot, room, result, only_alive=True, exclude={callback.from_user.id}
    )
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        card_screen_text(room, callback.from_user.id),
        card_screen(room, callback.from_user.id),
    )


@router.callback_query(F.data == "sp:apply")
async def cb_special_apply(callback: CallbackQuery) -> None:
    """Применить особую карту без цели."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            result = eng.use_special_card(room, callback.from_user.id, None)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)

    await callback.answer("🃏 Карта применена")
    await broadcast_to_room(callback.bot, room, result, only_alive=True)
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        card_screen_text(room, callback.from_user.id),
        card_screen(room, callback.from_user.id),
    )


@router.callback_query(F.data == "sp:cancel")
async def cb_special_cancel(callback: CallbackQuery) -> None:
    """Отменить применение карты."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await upsert_screen(
        callback.bot,
        room,
        callback.from_user.id,
        card_screen_text(room, callback.from_user.id),
        card_screen(room, callback.from_user.id),
    )