"""
Сквозная проверка бота без Telegram и без pytest.

Прогоняет полный игровой цикл через сервисный слой с настоящей SQLite:
создание комнаты -> лобби -> старт -> раскрытие карт -> обсуждение ->
голосование -> выбывание -> следующий раунд -> финал -> статистика.

Bot подменяется fake-объектом, который запоминает отправленные сообщения.

Запуск:  python tests/check_flow.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db.store import store  # noqa: E402
from game import engine as eng  # noqa: E402
from game.state import Phase, theme_for_round  # noqa: E402
from services import actions  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    mark = "OK  " if ok else "FAIL"
    print(f"{mark} {name}" + (f"  [{detail}]" if detail and not ok else ""))


class FakeSession:
    async def close(self) -> None:
        return None


class FakeMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class FakeBot:
    """Подмена aiogram.Bot: копит сообщения, поддерживает edit/answer."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.answers: list[str] = []
        self._msg_id = 0
        self.session = FakeSession()

    async def send_message(self, chat_id, text, reply_markup=None,
                           disable_notification=True, **kwargs):
        self._msg_id += 1
        self.sent.append({
            "chat_id": chat_id, "text": text,
            "markup": reply_markup, "id": self._msg_id,
        })
        return FakeMessage(self._msg_id)

    async def edit_message_text(self, chat_id, message_id, text,
                                reply_markup=None, **kwargs):
        self.edits.append({
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "markup": reply_markup,
        })
        return FakeMessage(message_id)

    async def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        self.answers.append(text or "")
        return True

    async def get_me(self):
        return type("Me", (), {
            "id": 999, "is_bot": True,
            "first_name": "BunkerBot", "username": "bunker_flow_bot",
        })()

    async def delete_webhook(self, **kwargs):
        return True

    # удобные выборки
    def texts_to(self, user_id: int) -> list[str]:
        return [m["text"] for m in self.sent if m["chat_id"] == user_id]

    def last_text(self) -> str:
        return self.sent[-1]["text"] if self.sent else ""


def text_has(messages: list[str], needle: str) -> bool:
    return any(needle in m for m in messages)


async def main() -> int:
    tmpdir = os.path.join(ROOT, "tests")
    db_file = os.path.join(tmpdir, "_flow_test.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_file + suffix)
        except FileNotFoundError:
            pass

    await store.connect(db_path=f"sqlite+aiosqlite:///{db_file}")
    bot = FakeBot()

    # --- комната и лобби ---------------------------------------------------
    room = eng.create_room(code="FLOW1", host_id=1, host_name="Хост")
    for uid in range(2, 6):
        eng.add_player(room, uid, f"Игрок{uid}")
    await store.save_room(room)

    await actions.refresh_lobby(bot, room)
    check("лобби разослано всем", len(bot.sent) >= 5, f"sent={len(bot.sent)}")
    check("в лобби есть код комнаты", "FLOW1" in bot.last_text(), bot.last_text()[:60])

    # --- старт игры --------------------------------------------------------
    await actions.start_game(bot, room)
    check("фаза после старта = REVEAL", room.phase == Phase.REVEAL, str(room.phase))
    check("карты розданы всем", all(len(p.cards) == 8 for p in room.players.values()))
    check("катастрофа и бункер заполнены", bool(room.disaster) and bool(room.bunker))
    check("тема 1-го раунда — профессия", theme_for_round(room.round_no) == "profession")
    host_texts = bot.texts_to(1)
    check("хост получил сводку миссии", text_has(host_texts, "Сводка миссии"), )

    # --- раскрытие карт ----------------------------------------------------
    for uid in list(room.players):
        eng.reveal_card(room, uid, "profession")
        await actions.after_reveal(bot, room, room.players[uid], "profession")
    check("все раскрыли → обсуждение", room.phase == Phase.DISCUSSION, str(room.phase))
    check("объявление раскрытия ушло", text_has(bot.texts_to(1), "раскрывает"))

    # --- голосование -------------------------------------------------------
    await actions.open_voting(bot, room)
    check("фаза голосования", room.phase == Phase.VOTING, str(room.phase))
    check("бюллетени разосланы", text_has(bot.texts_to(1), "Голосование"))

    # голосуем против 5-го
    for uid in (1, 2, 3, 4):
        eng.vote(room, uid, 5)
    await actions.resolve_voting_flow(bot, room)
    check("5-й выбыл", not room.players[5].alive)
    check("раунд стал 2-м", room.round_no == 2, str(room.round_no))
    check("фаза снова REVEAL", room.phase == Phase.REVEAL, str(room.phase))
    check("объявлено выбывание", text_has(bot.texts_to(1), "покидает бункер"))

    # --- добиваем до финала ------------------------------------------------
    guard = 0
    while room.phase != Phase.FINISHED and guard < 12:
        guard += 1
        print(f"  [шаг {guard}] фаза={room.phase.value} раунд={room.round_no}")
        # раскрываем текущую тему
        theme = theme_for_round(room.round_no) or "fact"
        for p in list(room.alive_players):
            if theme not in p.revealed:
                eng.reveal_card(room, p.user_id, theme)
                await actions.after_reveal(bot, room, p, theme)
        print(f"  [шаг {guard}] после раскрытия фаза={room.phase.value}")
        await actions.open_voting(bot, room)
        print(f"  [шаг {guard}] после открытия голосования фаза={room.phase.value}")
        alive = list(room.alive_players)
        victim = alive[-1].user_id
        for p in alive:
            if p.user_id != victim:
                eng.vote(room, p.user_id, victim)
        await actions.resolve_voting_flow(bot, room)
        print(f"  [шаг {guard}] после подсчёта фаза={room.phase.value} "
              f"живых={len(list(room.alive_players))}")

    check("игра дошла до финала", room.phase == Phase.FINISHED, str(room.phase))
    check("есть выжившие", len(room.winner_ids) > 0, str(room.winner_ids))
    check("текст финала отправлен", text_has(bot.texts_to(1), "выжил") or
          text_has(bot.texts_to(1), "Игра окончена"))

    # --- статистика и БД ---------------------------------------------------
    winner = room.winner_ids[0]
    stats = await store.get_user_stats(winner)
    loser = next(p.user_id for p in room.players.values() if p.user_id not in room.winner_ids)
    loser_stats = await store.get_user_stats(loser)
    check("победителю записан win", stats is not None and stats.get("wins", 0) >= 1, str(stats))
    check("проигравшему записан loss",
          loser_stats is not None and loser_stats.get("games", 0) >= 1, str(loser_stats))

    left = await store.get_user_room_code(1)
    check("игроки освобождены из комнаты", left is None, str(left))

    # сохранение/загрузка комнаты
    restored = eng.GameRoom.from_dict(room.to_dict())
    check("сериализация комнаты", restored.code == room.code and restored.phase == room.phase)

    await store.close()

    failed = [c for c in CHECKS if not c[1]]
    print()
    print(f"Итого: {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
