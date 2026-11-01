"""
Стартовый хендлер, главное меню и информационные экраны.

Содержит:
- /start (обычный и с deep-link room_<код>);
- информационные экраны: правила, о боте, личная статистика;
- создание комнаты и переход к экрану настроек.
"""

from __future__ import annotations

import logging
import re

from aiogram import Router, F
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from db.store import store
from game import engine as eng
from game.state import Phase
from game.registry import register, generate_code, get, get_by_user, lock_for
from keyboards import main_menu, back_to_menu, join_prompt
from keyboards.rooms import room_screen
from services.notifier import broadcast_to_room, safe_send
from states import Form

logger = logging.getLogger(__name__)
router = Router()

# deep-link вида: /start room_ABCDE
_ROOM_LINK_RE = re.compile(r"^room_([A-HJ-NP-Z2-9]{5})$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject,
                             state: FSMContext) -> None:
    """Вход в комнату по deep-link (t.me/<bot>?start=room_<код>)."""
    await state.clear()
    payload = (command.args or "").strip()
    match = _ROOM_LINK_RE.match(payload)
    if not match:
        await _show_main_menu(message)
        return

    code = match.group(1).upper()
    user = message.from_user

    # один пользователь — одна активная комната (проверяем и память, и БД)
    if get_by_user(user.id) is not None or await store.get_user_room_code(user.id):
        await message.answer(
            "⚠️ <b>Ты уже состоишь в комнате</b>\n\n"
            "Сначала выйди из неё, потом присоединяйся к новой.",
            reply_markup=back_to_menu(),
        )
        return

    async with lock_for(code):
        room = get(code) or await store.get_room_by_code(code)
        if room is None:
            await message.answer(
                f"❌ <b>Комната <code>{code}</code> не найдена</b>\n\n"
                "Возможно, код устарел или комната закрыта.",
                reply_markup=main_menu(),
            )
            return
        register(room)

        if room.phase != Phase.LOBBY:
            await message.answer(
                "❌ <b>Игра уже началась</b>\n\n"
                "К сожалению, присоединиться к запущенной игре нельзя.",
                reply_markup=main_menu(),
            )
            return

        if len(room.players) >= room.settings.max_players:
            await message.answer("❌ <b>Комната заполнена.</b>", reply_markup=main_menu())
            return

        try:
            eng.add_player(
                room=room,
                user_id=user.id,
                full_name=user.full_name,
                username=user.username,
            )
        except eng.GameError as exc:
            await message.answer(f"❌ {exc}", reply_markup=main_menu())
            return

        await store.save_room(room)

    await message.answer(
        _lobby_text(room, user.id),
        reply_markup=_lobby_kb(room, user.id),
    )
    # уведомляем остальных
    await broadcast_to_room(
        message.bot,
        room,
        f"🔔 <b>{_esc(user.full_name)}</b> присоединился к комнате "
        f"<code>{room.code}</code>",
        exclude={user.id},
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """/start без аргументов — главное меню (или подсказка об активной комнате)."""
    await state.clear()
    await _show_main_menu(message)


async def _show_main_menu(message: Message) -> None:
    """Отправить главное меню."""
    await message.answer(
        "<b>👋 Добро пожаловать в «Бункер»</b>\n\n"
        "<i>Постапокалипсис уже случился. Осталось решить, кого взять с собой.</i>\n\n"
        "🎮 <b>Создать комнату</b> — и позвать друзей по коду или ссылке\n"
        "🔑 <b>Войти по коду</b> — если тебя уже позвали",
        reply_markup=main_menu(),
    )


# ---------------------------------------------------------------------------
# Информационные экраны
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:rules")
async def cb_rules(callback: CallbackQuery) -> None:
    """Правила игры."""
    await callback.answer()
    await callback.message.edit_text(
        "<b>📜 Правила «Бункера»</b>\n\n"
        "<blockquote>Игроков: 4–12. Мест в бункере — ровно половина (округление вниз).</blockquote>\n"
        "1️⃣ <b>Раскрытие.</b> Каждый игрок по очереди открывает одну свою карту. "
        "В первом раунде — профессию.\n"
        "2️⃣ <b>Обсуждение.</b> Идёт таймер. Убеждай, договаривайся, блефуй.\n"
        "3️⃣ <b>Голосование.</b> Каждый голосует против одного игрока. За себя нельзя.\n"
        "4️⃣ <b>Выбывание.</b> Проигравший покидает бункер, его карты раскрываются.\n\n"
        "⚖️ <b>Ничья</b> → переголосование между лидерами. Повторная ничья → решает хост.\n"
        "🏁 <b>Финал</b> — когда живых остаётся ровно столько, сколько мест.\n\n"
        "🃏 <b>Особые карты</b> (если включены) дают разовое действие: обмен картой, "
        "иммунитет, двойной голос, подглядывание и другое.",
        reply_markup=back_to_menu(),
    )


@router.callback_query(F.data == "menu:about")
async def cb_about(callback: CallbackQuery) -> None:
    """О боте."""
    await callback.answer()
    await callback.message.edit_text(
        "<b>🤖 Бункер-бот</b> <i>v1.0</i>\n\n"
        "Бот для игры в «Бункер» с друзьями прямо в личных сообщениях.\n\n"
        "🛠 Стек: Python 3.11, aiogram 3, SQLite (aiosqlite)\n"
        "💾 Прогресс игр сохраняется и переживает перезапуск бота.",
        reply_markup=back_to_menu(),
    )


@router.callback_query(F.data == "menu:stats")
async def cb_my_stats(callback: CallbackQuery) -> None:
    """Личная статистика."""
    await callback.answer()
    stats = await store.get_user_stats(callback.from_user.id)
    await callback.message.edit_text(
        "<b>📊 Твоя статистика</b>\n\n"
        f"🎮 Сыграно игр: <b>{stats['games']}</b>\n"
        f"🏆 Побед: <b>{stats['wins']}</b>",
        reply_markup=back_to_menu(),
    )


@router.callback_query(F.data == "menu:back")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню."""
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "<b>🏠 Главное меню</b>\n\n<i>Что дальше?</i>",
        reply_markup=main_menu(),
    )


# ---------------------------------------------------------------------------
# Создание комнаты и ввод кода
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:create")
async def cb_create_room(callback: CallbackQuery) -> None:
    """Создать комнату и показать экран настроек."""
    await callback.answer()
    user = callback.from_user

    if get_by_user(user.id) is not None or await store.get_user_room_code(user.id):
        await callback.message.edit_text(
            "⚠️ <b>Ты уже состоишь в комнате</b>\n\n"
            "Сначала покинь её.",
            reply_markup=back_to_menu(),
        )
        return

    code = generate_code()
    room = eng.create_room(
        code=code,
        host_id=user.id,
        host_name=user.full_name,
        host_username=user.username,
    )
    register(room)
    await store.save_room(room)

    bot_info = await callback.bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=room_{code}"

    await callback.message.edit_text(
        _room_screen_text(room, deep_link),
        reply_markup=room_screen(
            discussion=room.settings.discussion_seconds,
            players=room.settings.max_players,
            special_cards=room.settings.special_cards_on,
            disaster_mode=room.settings.disaster_mode,
            deep_link=deep_link,
        ),
    )


@router.callback_query(F.data == "menu:join")
async def cb_join_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Попросить ввести код комнаты."""
    await callback.answer()

    if get_by_user(callback.from_user.id) is not None or \
            await store.get_user_room_code(callback.from_user.id):
        await callback.message.edit_text(
            "⚠️ <b>Ты уже состоишь в комнате</b>",
            reply_markup=back_to_menu(),
        )
        return

    await state.set_state(Form.waiting_room_code)
    await callback.message.edit_text(
        "<b>🔑 Введи код комнаты</b>\n\n"
        "Код состоит из 5 символов — буквы и цифры.\n"
        "<i>Просто отправь его сообщением.</i>",
        reply_markup=join_prompt(),
    )


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _esc(text: str) -> str:
    """Экранирование HTML для пользовательских данных."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _lobby_text(room, viewer_id: int) -> str:
    """Текст лобби для игрока."""
    players = "\n".join(
        f"  {'👑 ' if p.is_host else '▫️ '}{_esc(p.full_name)}"
        for p in sorted(room.players.values(), key=lambda x: x.join_index)
    )
    return (
        f"🏠 <b>Комната <code>{room.code}</code></b>\n\n"
        f"👥 Игроки: <b>{len(room.players)}/{room.settings.max_players}</b>\n"
        f"{players}\n\n"
        f"⏱ Обсуждение: <b>{room.settings.discussion_seconds} сек</b>\n"
        f"🃏 Особые карты: <b>{'вкл' if room.settings.special_cards_on else 'выкл'}</b>"
    )


def _lobby_kb(room, viewer_id: int):
    """Клавиатура лобби."""
    from keyboards import lobby
    return lobby(room, viewer_id)


def _room_screen_text(room, deep_link: str) -> str:
    """Текст экрана комнаты (настроек) для хоста."""
    return (
        f"🎮 <b>Комната создана</b>\n\n"
        f"Код доступа: <code>{room.code}</code>\n"
        f"Ссылка: <code>{deep_link}</code>\n\n"
        f"👥 Игроки: <b>{len(room.players)}/{room.settings.max_players}</b>\n"
        f"⏱ Обсуждение: <b>{room.settings.discussion_seconds} сек</b>\n"
        f"🃏 Особые карты: <b>{'вкл' if room.settings.special_cards_on else 'выкл'}</b>\n\n"
        f"<i>Нажми «Поделиться», чтобы позвать друзей.</i>"
    )


__all__ = ["router"]
