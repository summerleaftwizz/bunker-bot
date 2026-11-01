"""
Оркестрация игровых сценариев.

Здесь собраны переходы между фазами и рассылки, чтобы хендлеры оставались
тонкими: получили событие из Telegram → вызвали функцию движка → вызвали
функцию отсюда. Вся работа с текстами и «экранами» игроков — тоже здесь.
"""

from __future__ import annotations

import logging
import re
import time

from aiogram import Bot

from db.store import store
from game import engine as eng
from game.state import (
    Phase,
    CARD_ICONS,
    CARD_LABELS,
    SPECIAL,
    theme_for_round,
)
from data.special_cards import SPECIAL_CARDS_MAP
from keyboards import (
    card_screen,
    voting,
    tiebreak,
    after_result,
    lobby as lobby_kb,
)
from services.notifier import safe_edit, safe_send, send_tracked, broadcast_to_room

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def esc(text: object) -> str:
    """Экранирование HTML для любых пользовательских данных."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _strip_tags(text: str) -> str:
    """Убрать HTML-теги (для логов и статистики)."""
    return re.sub(r"<[^>]+>", "", text)


def theme_label(room) -> str:
    """Человекочитаемая тема текущего раунда раскрытия."""
    theme = theme_for_round(room.round_no)
    if theme is None:
        return "любую закрытую карту"
    return CARD_LABELS.get(theme, theme)


async def upsert_screen(bot: Bot, room, user_id: int, text: str,
                        kb=None) -> None:
    """
    Показать экран игроку: отредактировать прежнее сообщение или отправить новое.

    Так лобби и карточка игрока не спамят новыми сообщениями.
    """
    mid = room.ui_msg.get(user_id)
    if mid:
        if await safe_edit(bot, user_id, mid, text, kb):
            return
    new_id = await send_tracked(bot, user_id, text, kb)
    if new_id is None:
        player = room.players.get(user_id)
        if player is not None:
            player.disconnected = True
    else:
        room.ui_msg[user_id] = new_id


async def announce(bot: Bot, room, text: str, only_alive: bool = True,
                   exclude: set[int] | None = None) -> None:
    """Разослать общее событие всем игрокам комнаты."""
    await broadcast_to_room(
        bot, room, text, only_alive=only_alive, exclude=exclude or set()
    )


# ---------------------------------------------------------------------------
# Тексты экранов
# ---------------------------------------------------------------------------
def lobby_text(room, viewer_id: int) -> str:
    """Текст лобби."""
    lines = [
        f"🏠 <b>Комната <code>{room.code}</code></b>",
        "",
        f"👥 Игроки: <b>{len(room.players)}/{room.settings.max_players}</b>",
    ]
    for p in sorted(room.players.values(), key=lambda x: x.join_index):
        mark = "👑" if p.is_host else "▫️"
        lines.append(f"  {mark} {esc(p.full_name)}")
    lines.append("")
    lines.append(f"⏱ Обсуждение: <b>{room.settings.discussion_seconds} сек</b>")
    lines.append(
        "🃏 Особые карты: "
        + ("<b>вкл</b>" if room.settings.special_cards_on else "<b>выкл</b>")
    )
    lines.append("")
    lines.append(
        "<i>Ждём игроков. Хост нажимает «Старт», когда все в сборе "
        f"(нужно от 4 до {room.settings.max_players}).</i>"
    )
    return "\n".join(lines)


def card_screen_text(room, viewer_id: int) -> str:
    """Личная карточка игрока: закрытые карты — 🔒, открытые — 🔓."""
    player = room.players[viewer_id]
    lines = [f"🃏 <b>Твои карты</b>", ""]
    lines.append(f"👤 <b>{esc(player.full_name)}</b>")
    status = "в игре" if player.alive else "выбыл"
    lines.append(f"<i>Статус: {status}</i>")
    lines.append("")

    for attr in (
        "profession",
        "gender_age",
        "health",
        "hobby",
        "phobia",
        "baggage",
        "fact",
    ):
        value = player.cards.get(attr)
        if value is None:
            continue
        icon = CARD_ICONS.get(attr, "•")
        label = CARD_LABELS.get(attr, attr)
        if attr in player.revealed:
            lines.append(f"{icon} <b>{label}:</b> {esc(value)} 🔓")
        else:
            lines.append(f"{icon} <b>{label}:</b> <i>скрыто</i> 🔒")

    key = player.special_key
    if key:
        title, description, needs_target = SPECIAL_CARDS_MAP.get(
            key, ("Особая карта", "", False)
        )
        used = " <i>(использована)</i>" if player.special_used else ""
        lines.append("")
        lines.append(f"🃏 <b>Особая карта:</b> {esc(title)}{used}")
        if not player.special_used:
            lines.append(f"<blockquote>{esc(description)}</blockquote>")

    lines.append("")
    lines.append(
        f"📍 Раунд <b>{room.round_no}</b> · фаза <b>{_phase_label(room.phase)}</b>"
    )
    if room.phase == Phase.REVEAL and player.alive:
        lines.append(f"🔓 Сейчас раскрывается: <b>{theme_label(room)}</b>")
    lines.append("")
    lines.append("<i>Эти карты видишь только ты. Раскрывай их с умом.</i>")
    return "\n".join(lines)


def mission_text(room) -> str:
    """Сводка катастрофы и бункера."""
    alive = len([p for p in room.players.values() if p.alive])
    return (
        "<b>☢️ Сводка миссии</b>\n\n"
        f"{room.disaster}\n\n"
        "───────────────\n"
        f"{room.bunker}\n\n"
        f"👥 Живых: <b>{alive}</b> · мест: <b>{room.capacity}</b>\n"
        f"🔁 Раунд: <b>{room.round_no}</b>"
    )


def public_reveal_text(room, player, attr: str) -> str:
    """Строка публичного раскрытия карты игроком."""
    icon = CARD_ICONS.get(attr, "•")
    label = CARD_LABELS.get(attr, attr)
    return (
        f"🔓 <b>{esc(player.full_name)}</b> раскрывает "
        f"{icon} <b>{label}</b>:\n"
        f"<blockquote>{esc(player.cards.get(attr, '—'))}</blockquote>"
    )


def _phase_label(phase: Phase) -> str:
    return {
        Phase.LOBBY: "лобби",
        Phase.REVEAL: "раскрытие",
        Phase.DISCUSSION: "обсуждение",
        Phase.VOTING: "голосование",
        Phase.RESULT: "результат",
        Phase.FINISHED: "финал",
    }.get(phase, phase.value)


# ---------------------------------------------------------------------------
# Экраны
# ---------------------------------------------------------------------------
async def refresh_lobby(bot: Bot, room) -> None:
    """Обновить экран лобби у всех игроков."""
    for uid in list(room.players.keys()):
        await upsert_screen(bot, room, uid, lobby_text(room, uid), lobby_kb(room, uid))
    await store.save_room(room)


async def send_card_screen(bot: Bot, room, user_id: int) -> None:
    """Показать игроку его карточку."""
    if user_id not in room.players:
        return
    await upsert_screen(
        bot, room, user_id, card_screen_text(room, user_id), card_screen(room, user_id)
    )


async def send_card_screens_to_all(bot: Bot, room) -> None:
    """Разослать карточки всем игрокам."""
    for uid in list(room.players.keys()):
        await send_card_screen(bot, room, uid)


# ---------------------------------------------------------------------------
# Фазы
# ---------------------------------------------------------------------------
async def start_game(bot: Bot, room) -> None:
    """
    Запустить игру: раздать карты, показать катастрофу и бункер, раздать карточки.

    Бросает eng.GameError, если старт невозможен (мало игроков и т.п.).
    """
    eng.start_game(room)
    await store.save_room(room)

    await announce(bot, room, mission_text(room), only_alive=False)
    await announce(
        bot,
        room,
        f"🎮 <b>Игра началась!</b>\n\n"
        f"👥 Игроков: <b>{len(room.players)}</b>, мест в бункере: <b>{room.capacity}</b>\n"
        f"🔓 Первый раунд: раскрывается <b>профессия</b>.\n\n"
        f"<i>Твои карты — в личном экране ниже.</i>",
        only_alive=False,
    )
    await begin_reveal_round(bot, room)


async def begin_reveal_round(bot: Bot, room) -> None:
    """Начать раунд раскрытия: объявить тему и разослать карточки."""
    await announce(
        bot,
        room,
        f"🔄 <b>Раунд {room.round_no}</b>\n\n"
        f"Раскрытие: <b>{theme_label(room)}</b>\n"
        f"<i>Каждый живой игрок раскрывает одну карту.</i>",
    )
    await send_card_screens_to_all(bot, room)
    await store.save_room(room)


async def after_reveal(bot: Bot, room, player, attr: str) -> None:
    """Обработать раскрытие карты: объявить и, если все готовы, начать обсуждение."""
    await announce(bot, room, public_reveal_text(room, player, attr))
    await send_card_screen(bot, room, player.user_id)

    if eng.all_revealed_for_round(room):
        await begin_discussion(bot, room)
    else:
        await store.save_room(room)


async def begin_discussion(bot: Bot, room) -> None:
    """Перейти к обсуждению и запустить таймер."""
    eng.goto_discussion(room)
    seconds = room.settings.discussion_seconds
    await announce(
        bot,
        room,
        f"🗣 <b>Обсуждение началось</b>\n\n"
        f"⏱ На всё про всё: <b>{seconds} сек</b>\n"
        f"<i>Раунд {room.round_no}. Убеждай, торгуйся, блефуй.</i>",
        only_alive=True,
    )
    await store.save_room(room)


async def open_voting(bot: Bot, room) -> None:
    """Открыть голосование и разослать бюллетени."""
    eng.open_voting(room)
    await announce(
        bot,
        room,
        "🗳 <b>Голосование!</b>\n\n"
        "Выбери, кто покинет бункер. За себя голосовать нельзя.\n"
        "<i>Ждём голоса всех живых игроков.</i>",
        only_alive=True,
    )
    for p in room.alive_players:
        await upsert_screen(
            bot, room, p.user_id,
            _vote_screen_text(room, p.user_id),
            voting(room, p.user_id),
        )
    await store.save_room(room)


def _vote_screen_text(room, viewer_id: int) -> str:
    """Текст экрана голосования."""
    voted = len(room.votes)
    alive = len(room.alive_players)
    lines = [
        "🗳 <b>Голосование</b>",
        "",
        f"Проголосовали: <b>{voted}/{alive}</b>",
        f"Раунд: <b>{room.round_no}</b>",
    ]
    if room.vote_round > 1:
        lines.append("♻️ <b>Переголосование между лидерами</b>")
    if room.restricted_targets:
        names = ", ".join(
            esc(room.players[uid].full_name)
            for uid in room.restricted_targets
            if uid in room.players
        )
        lines.append(f"🎯 Кандидаты: {names}")
    if viewer_id in room.votes:
        lines.append("")
        lines.append("✅ Твой голос принят. Ждём остальных.")
    lines.append("")
    lines.append("<i>Голоса анонимны до подсчёта.</i>")
    return "\n".join(lines)


async def refresh_vote_screens(bot: Bot, room) -> None:
    """Обновить бюллетени после чьего-то голоса."""
    for p in room.alive_players:
        await upsert_screen(
            bot, room, p.user_id,
            _vote_screen_text(room, p.user_id),
            voting(room, p.user_id),
        )
    await store.save_room(room)


async def resolve_voting_flow(bot: Bot, room) -> None:
    """Подсчитать голоса и обработать исход."""
    outcome = eng.resolve_voting(room)
    kind = outcome["type"]

    if kind == "eliminated":
        victim_id = outcome["leader_id"]
        victim = room.players[victim_id]
        counts = outcome["counts"]

        # публично раскрываем все карты выбывшего
        cards_lines = []
        for attr in victim.revealed:
            icon = CARD_ICONS.get(attr, "•")
            label = CARD_LABELS.get(attr, attr)
            value = victim.cards.get(attr, "—")
            if attr == SPECIAL:
                info = SPECIAL_CARDS_MAP.get(value)
                value = info[0] if info else value
            cards_lines.append(f"{icon} <b>{label}:</b> {esc(value)}")

        await announce(
            bot,
            room,
            f"⚰️ <b>{esc(victim.full_name)} покидает бункер</b>\n\n"
            f"Голосов против: <b>{counts.get(victim_id, 0)}</b>\n\n"
            f"<b>Раскрытые карты:</b>\n" + "\n".join(cards_lines),
            only_alive=False,
        )

        finished = eng.continue_after_result(room)
        await store.save_room(room)

        if finished:
            await finish_game(bot, room)
            return

        # следующий раунд
        await begin_reveal_round(bot, room)
        return

    if kind == "revote":
        leaders = outcome["leaders"]
        names = ", ".join(esc(room.players[uid].full_name) for uid in leaders if uid in room.players)
        await announce(
            bot,
            room,
            f"⚖️ <b>Ничья!</b>\n\n"
            f"Лидеры: {names}\n"
            f"<i>Переголосование между ними. Голосуем ещё раз.</i>",
            only_alive=True,
        )
        await store.save_room(room)
        for p in room.alive_players:
            await upsert_screen(
                bot, room, p.user_id,
                _vote_screen_text(room, p.user_id),
                voting(room, p.user_id),
            )
        return

    if kind == "host_tiebreak":
        leaders = outcome["leaders"]
        names = ", ".join(esc(room.players[uid].full_name) for uid in leaders if uid in room.players)
        host = room.players.get(room.host_id)
        await announce(
            bot,
            room,
            f"⚖️ <b>Повторная ничья!</b>\n\n"
            f"Лидеры: {names}\n"
            f"<i>Решает хост.</i>",
            only_alive=True,
        )
        if host is not None:
            await upsert_screen(
                bot,
                room,
                host.user_id,
                f"⚖️ <b>Повторная ничья</b>\n\nЛидеры: {names}\n\n"
                f"<i>Выбери, кто покинет бункер.</i>",
                tiebreak(room),
            )
        await store.save_room(room)
        return

    logger.warning("Неизвестный исход голосования: %s", outcome)


async def finish_game(bot: Bot, room) -> None:
    """Показать финал, записать статистику и освободить игроков."""
    text = room.finish_text or "<b>Игра окончена</b>"

    await announce(bot, room, text, only_alive=False)

    winners = set(room.winner_ids)
    players_log = []
    for p in room.players.values():
        won = p.user_id in winners
        try:
            await store.bump_stats(p.user_id, won)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось обновить статистику %s", p.user_id)
        players_log.append({
            "user_id": p.user_id,
            "full_name": p.full_name,
            "won": won,
            "cards": p.cards,
        })

    try:
        await store.log_game(
            code=room.code,
            disaster=_strip_tags(room.disaster),
            survivors=room.winner_ids,
            players=players_log,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось записать игру в лог")

    # сначала сохраняем финальное состояние комнаты,
    # затем освобождаем игроков (иначе save вставит их обратно)
    await store.save_room(room)
    try:
        await store.clear_players(room.code)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось очистить участников комнаты %s", room.code)

    # финальные кнопки
    for uid in list(room.players.keys()):
        is_winner = uid in winners
        await upsert_screen(
            bot, room, uid,
            ("🏆 <b>Ты выжил!</b>\n\n" if is_winner else "💀 <b>Ты не выжил.</b>\n\n")
            + "<i>Спасибо за игру!</i>",
            after_result(uid, room.host_id == uid, True),
        )
