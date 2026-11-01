"""
Обработчики комнаты: настройки, старт, закрытие, вход по коду, лобби.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.special_cards import SPECIAL_CARDS_MAP  # noqa: F401 (используется в game.py)
from db.store import store
from game import engine as eng
from game.registry import register, get, get_by_user, lock_for, unregister
from game.state import Phase, MIN_PLAYERS, MAX_PLAYERS
from keyboards import room_screen, lobby, main_menu, back_to_menu
from services import actions
from services.notifier import safe_send, broadcast_to_room
from states import Form

logger = logging.getLogger(__name__)
router = Router()

_DISCUSSION_OPTIONS = (30, 60, 90, 120, 180)


# ---------------------------------------------------------------------------
# Настройки комнаты (хост)
# ---------------------------------------------------------------------------
def _host_room(callback: CallbackQuery):
    """Комната, где пользователь — хост (или None)."""
    room = get_by_user(callback.from_user.id)
    if room is None or room.host_id != callback.from_user.id:
        return None
    return room


async def _render_room_screen(bot, room, chat_id: int, message_id: int) -> None:
    """Перерисовать экран настроек комнаты на текущем сообщении."""
    bot_info = await bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=room_{room.code}"
    text = (
        f"🎮 <b>Комната создана</b>\n\n"
        f"Код доступа: <code>{room.code}</code>\n"
        f"Ссылка: <code>{deep_link}</code>\n\n"
        f"👥 Игроки: <b>{len(room.players)}/{room.settings.max_players}</b>\n"
        f"⏱ Обсуждение: <b>{room.settings.discussion_seconds} сек</b>\n"
        f"🃏 Особые карты: <b>{'вкл' if room.settings.special_cards_on else 'выкл'}</b>\n\n"
        f"<i>Слева — настройки, ниже — старт и управление.</i>"
    )
    kb = room_screen(
        discussion=room.settings.discussion_seconds,
        players=room.settings.max_players,
        special_cards=room.settings.special_cards_on,
        disaster_mode=room.settings.disaster_mode,
        deep_link=deep_link,
    )
    await actions.upsert_screen(bot, room, chat_id, text, kb)
    if message_id and chat_id not in room.ui_msg:
        room.ui_msg[chat_id] = message_id
    await store.save_room(room)


@router.callback_query(F.data == "room:time")
async def cb_room_time(callback: CallbackQuery) -> None:
    """Циклично менять таймер обсуждения."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Это может делать только хост.", show_alert=True)
        return
    current = room.settings.discussion_seconds
    options = _DISCUSSION_OPTIONS
    idx = options.index(current) if current in options else 1
    room.settings.discussion_seconds = options[(idx + 1) % len(options)]
    await store.save_room(room)
    await _render_room_screen(callback.bot, room, callback.from_user.id,
                              callback.message.message_id)
    await callback.answer(f"⏱ Таймер: {room.settings.discussion_seconds} сек")


@router.callback_query(F.data == "room:players")
async def cb_room_players(callback: CallbackQuery) -> None:
    """Циклично менять число игроков (4–12)."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Это может делать только хост.", show_alert=True)
        return
    current = room.settings.max_players
    room.settings.max_players = current + 1 if current < MAX_PLAYERS else MIN_PLAYERS
    await store.save_room(room)
    await _render_room_screen(callback.bot, room, callback.from_user.id,
                              callback.message.message_id)
    await callback.answer(f"👥 Игроков: {room.settings.max_players}")


@router.callback_query(F.data == "room:special")
async def cb_room_special(callback: CallbackQuery) -> None:
    """Переключить особые карты."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Это может делать только хост.", show_alert=True)
        return
    room.settings.special_cards_on = not room.settings.special_cards_on
    await store.save_room(room)
    await _render_room_screen(callback.bot, room, callback.from_user.id,
                              callback.message.message_id)
    await callback.answer("🃏 Особые карты: " +
                          ("вкл" if room.settings.special_cards_on else "выкл"))


@router.callback_query(F.data == "room:disaster")
async def cb_room_disaster(callback: CallbackQuery) -> None:
    """Переключить режим катастроф."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Это может делать только хост.", show_alert=True)
        return
    room.settings.disaster_mode = (
        "classic" if room.settings.disaster_mode == "random" else "random"
    )
    await store.save_room(room)
    await _render_room_screen(callback.bot, room, callback.from_user.id,
                              callback.message.message_id)
    await callback.answer("🌪 Катастрофы: " +
                          ("случайные" if room.settings.disaster_mode == "random"
                           else "по порядку"))


# ---------------------------------------------------------------------------
# Старт и закрытие комнаты
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "room:start")
async def cb_room_start(callback: CallbackQuery) -> None:
    """Начать игру (аналог lobby:start)."""
    await _start_game(callback)


@router.callback_query(F.data == "lobby:start")
async def cb_lobby_start(callback: CallbackQuery) -> None:
    """Начать игру из лобби."""
    await _start_game(callback)


async def _start_game(callback: CallbackQuery) -> None:
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Старт может запустить только хост.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            await actions.start_game(callback.bot, room)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
    await callback.answer("🎮 Игра началась!")


@router.callback_query(F.data == "room:close")
async def cb_room_close(callback: CallbackQuery) -> None:
    """Закрыть комнату и удалить её."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Это может сделать только хост.", show_alert=True)
        return

    for uid in list(room.players.keys()):
        if uid != callback.from_user.id:
            await safe_send(callback.bot, uid, "🚫 <b>Комната закрыта хостом.</b>")

    async with lock_for(room.code):
        await store.delete_room(room.code)
        unregister(room.code)

    await callback.answer("🚫 Комната закрыта")
    await callback.message.edit_text(
        "🚫 <b>Комната закрыта</b>\n\nДо новых встреч!",
        reply_markup=main_menu(),
    )


# ---------------------------------------------------------------------------
# Лобби: показ, выход, кик, пинг хоста
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "lobby:show")
async def cb_lobby_show(callback: CallbackQuery) -> None:
    """Показать лобби (обычно после возврата из настроек)."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    await callback.answer()
    await actions.refresh_lobby(callback.bot, room)


@router.callback_query(F.data == "lobby:settings")
async def cb_lobby_settings(callback: CallbackQuery) -> None:
    """Из лобби открыть настройки комнаты."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Настройки доступны только хосту.", show_alert=True)
        return
    await callback.answer()
    await _render_room_screen(callback.bot, room, callback.from_user.id,
                              callback.message.message_id)


@router.callback_query(F.data == "lobby:leave")
async def cb_lobby_leave(callback: CallbackQuery) -> None:
    """Выйти из комнаты."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return

    user_id = callback.from_user.id
    was_host = room.host_id == user_id

    async with lock_for(room.code):
        try:
            eng.remove_player(room, user_id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)

        # комната опустела — удаляем
        if not room.players:
            await store.delete_room(room.code)
            unregister(room.code)
            await callback.answer("👋")
            await callback.message.edit_text(
                "🚪 <b>Ты вышел. Комната удалена.</b>",
                reply_markup=main_menu(),
            )
            return

        await actions.refresh_lobby(callback.bot, room)

    if was_host:
        await broadcast_to_room(
            callback.bot,
            room,
            "👑 <b>Хост покинул комнату.</b> Новый хост назначен автоматически.\n\n"
            "Ему переходит право старта.",
        )
    await callback.answer("🚪 Ты вышел")
    await callback.message.edit_text(
        "🚪 <b>Ты вышел из комнаты.</b>",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("lobby:kick:"))
async def cb_lobby_kick(callback: CallbackQuery) -> None:
    """Хост выгоняет игрока."""
    room = _host_room(callback)
    if room is None:
        await callback.answer("❌ Кикать может только хост.", show_alert=True)
        return

    try:
        target_id = int(callback.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка.", show_alert=True)
        return

    if target_id == callback.from_user.id:
        await callback.answer("❌ Нельзя кикнуть себя.", show_alert=True)
        return

    async with lock_for(room.code):
        try:
            eng.remove_player(room, target_id)
        except eng.GameError as exc:
            await callback.answer(f"❌ {exc}", show_alert=True)
            return
        await store.save_room(room)
        await actions.refresh_lobby(callback.bot, room)

    await safe_send(callback.bot, target_id, "🚫 <b>Тебя выгнали из комнаты.</b>")
    await callback.answer("🚫 Игрок кикнут")


@router.callback_query(F.data == "lobby:ping_host")
async def cb_lobby_ping_host(callback: CallbackQuery) -> None:
    """Позвать хоста (бросит лобби в чат)."""
    room = get_by_user(callback.from_user.id)
    if room is None:
        await callback.answer("❌ Комната не найдена.", show_alert=True)
        return
    host = room.players.get(room.host_id)
    if host is not None:
        await safe_send(
            callback.bot,
            host.user_id,
            f"🔔 <b>{callback.from_user.full_name}</b> зовёт тебя — "
            "все ждут старта!",
        )
    await callback.answer("🔔 Хост уведомлён")


# ---------------------------------------------------------------------------
# Вход по коду (текст)
# ---------------------------------------------------------------------------
@router.message(Form.waiting_room_code, F.text)
async def msg_join_by_code(message: Message, state: FSMContext) -> None:
    """Игрок ввёл код комнаты."""
    await state.clear()
    code = (message.text or "").strip().upper()

    # уже в комнате?
    if get_by_user(message.from_user.id) is not None or \
            await store.get_user_room_code(message.from_user.id):
        await message.answer("⚠️ <b>Ты уже состоишь в комнате.</b>",
                             reply_markup=main_menu())
        return

    async with lock_for(code):
        room = get(code) or await store.get_room_by_code(code)
        if room is None:
            await message.answer(f"❌ <b>Комната <code>{code}</code> не найдена.</b>",
                                 reply_markup=main_menu())
            return
        register(room)

        if room.phase != Phase.LOBBY:
            await message.answer("❌ <b>Игра уже началась.</b>", reply_markup=main_menu())
            return
        if len(room.players) >= room.settings.max_players:
            await message.answer("❌ <b>Комната заполнена.</b>", reply_markup=main_menu())
            return

        try:
            eng.add_player(
                room=room,
                user_id=message.from_user.id,
                full_name=message.from_user.full_name,
                username=message.from_user.username,
            )
        except eng.GameError as exc:
            await message.answer(f"❌ {exc}", reply_markup=main_menu())
            return

        await store.save_room(room)

    await actions.refresh_lobby(message.bot, room)
    await message.answer(f"✅ <b>Ты в комнате <code>{code}</code>.</b>",
                         reply_markup=back_to_menu())
    await broadcast_to_room(
        message.bot,
        room,
        f"🔔 <b>{message.from_user.full_name}</b> присоединился к комнате "
        f"<code>{code}</code>",
        exclude={message.from_user.id},
    )