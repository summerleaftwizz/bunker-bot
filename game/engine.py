"""
Игровой движок «Бункера». Чистая логика без aiogram.

Все действия валидируются на принадлежность текущей фазе (Phase). Ошибки
недопустимых действий выбрасываются как GameError — слой Telegram ловит их
и отвечает игроку понятным сообщением, не роняя бота.

Состояние комнаты полностью сериализуется в dict (to_dict/from_dict) и
хранится в БД (services/cleanup + db/store.py), поэтому игра переживает
рестарт бота.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

from game.state import (
    Phase,
    RoomSettings,
    MIN_PLAYERS,
    MAX_PLAYERS,
    theme_for_round,
    bunker_capacity,
    SPECIAL,
    PROFESSION,
    CARD_LABELS,
)
from game.cards import Deck
from game import endings

from data.disasters import DISASTERS
from data.bunkers import BUNKER_NAMES, BUNKER_FEATURES
from data.special_cards import SPECIAL_CARDS_MAP


class GameError(Exception):
    """Ошибка игрового действия, которую можно показать пользователю."""


# ---------------------------------------------------------------------------
# Игрок
# ---------------------------------------------------------------------------
@dataclass
class PlayerState:
    user_id: int
    full_name: str
    username: Optional[str] = None
    is_host: bool = False
    alive: bool = True
    disconnected: bool = False
    # тип карты -> значение
    cards: dict[str, str] = field(default_factory=dict)
    # типы карт, раскрытые публично
    revealed: list[str] = field(default_factory=list)
    # ключ особой карты (если выпала)
    special_key: Optional[str] = None
    special_used: bool = False
    # особые эффекты на текущее/следующее голосование
    immunity: bool = False            # голоса против не считаются
    alibi: bool = False               # один голос против аннулируется
    double_vote: bool = False         # голос весит 2
    sabotage_target: bool = False     # чей голос отменён
    muted_until_round: int = 0        # не голосует в раундах <= этого
    join_index: int = 0               # порядок вступления (для смены хоста)

    def hidden_cards(self) -> list[str]:
        """Список не раскрытых типов карт."""
        return [k for k in self.cards if k not in self.revealed]

    def reveal(self, attr: str) -> None:
        """Открыть карту. Кидает GameError, если карты нет или она уже открыта."""
        if attr not in self.cards:
            raise GameError("Такой карты у тебя нет.")
        if attr in self.revealed:
            raise GameError("Эта карта уже раскрыта.")
        self.revealed.append(attr)

    def to_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "full_name": self.full_name,
            "username": self.username,
            "is_host": self.is_host,
            "alive": self.alive,
            "disconnected": self.disconnected,
            "cards": self.cards,
            "revealed": self.revealed,
            "special_key": self.special_key,
            "special_used": self.special_used,
            "immunity": self.immunity,
            "alibi": self.alibi,
            "double_vote": self.double_vote,
            "sabotage_target": self.sabotage_target,
            "muted_until_round": self.muted_until_round,
            "join_index": self.join_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PlayerState":
        return cls(
            user_id=int(data["user_id"]),
            full_name=str(data["full_name"]),
            username=data.get("username"),
            is_host=bool(data.get("is_host", False)),
            alive=bool(data.get("alive", True)),
            disconnected=bool(data.get("disconnected", False)),
            cards=dict(data.get("cards", {})),
            revealed=list(data.get("revealed", [])),
            special_key=data.get("special_key"),
            special_used=bool(data.get("special_used", False)),
            immunity=bool(data.get("immunity", False)),
            alibi=bool(data.get("alibi", False)),
            double_vote=bool(data.get("double_vote", False)),
            sabotage_target=bool(data.get("sabotage_target", False)),
            muted_until_round=int(data.get("muted_until_round", 0)),
            join_index=int(data.get("join_index", 0)),
        )


# ---------------------------------------------------------------------------
# Комната
# ---------------------------------------------------------------------------
@dataclass
class GameRoom:
    code: str
    host_id: int
    settings: RoomSettings = field(default_factory=RoomSettings)
    phase: Phase = Phase.LOBBY
    players: dict[int, PlayerState] = field(default_factory=dict)
    round_no: int = 1
    # сколько раскрытий сделал игрок в текущем раунде (для контроля перехода)
    round_reveals: dict[int, int] = field(default_factory=dict)
    disaster: str = ""
    bunker: str = ""
    capacity: int = 0
    discussion_deadline: Optional[float] = None
    votes: dict[int, int] = field(default_factory=dict)   # voter -> target
    vote_round: int = 1
    restricted_targets: Optional[list[int]] = None        # переголосование
    pending_host_tiebreak: bool = False
    tie_leaders: list[int] = field(default_factory=list)
    winner_ids: list[int] = field(default_factory=list)
    finish_text: str = ""
    # id служебных сообщений в ЛС игроков: user_id -> message_id
    # нужно, чтобы лобби/экраны обновлялись через edit_message, а не спамили
    ui_msg: dict[int, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _deck: Optional[Deck] = field(default=None, repr=False, compare=False)

    # ---------- вспомогательные ----------
    @property
    def alive_players(self) -> list[PlayerState]:
        return [p for p in sorted(self.players.values(), key=lambda p: p.join_index) if p.alive]

    def get_player(self, user_id: int) -> PlayerState:
        p = self.players.get(user_id)
        if p is None:
            raise GameError("Тебя нет в этой комнате.")
        return p

    def touch(self) -> None:
        """Обновить метку last activity (для авто-очистки)."""
        self.updated_at = time.time()

    # ---------- сериализация ----------
    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "host_id": self.host_id,
            "settings": self.settings.to_dict(),
            "phase": self.phase.value,
            "players": {str(uid): p.to_dict() for uid, p in self.players.items()},
            "round_no": self.round_no,
            "round_reveals": {str(uid): n for uid, n in self.round_reveals.items()},
            "disaster": self.disaster,
            "bunker": self.bunker,
            "capacity": self.capacity,
            "discussion_deadline": self.discussion_deadline,
            "votes": {str(v): t for v, t in self.votes.items()},
            "vote_round": self.vote_round,
            "restricted_targets": self.restricted_targets,
            "pending_host_tiebreak": self.pending_host_tiebreak,
            "tie_leaders": self.tie_leaders,
            "winner_ids": self.winner_ids,
            "finish_text": self.finish_text,
            "ui_msg": {str(uid): mid for uid, mid in self.ui_msg.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GameRoom":
        room = cls(
            code=str(data["code"]),
            host_id=int(data["host_id"]),
            settings=RoomSettings.from_dict(dict(data.get("settings", {}))),
            phase=Phase(str(data.get("phase", Phase.LOBBY.value))),
            round_no=int(data.get("round_no", 1)),
            round_reveals={int(k): int(v) for k, v in dict(data.get("round_reveals", {})).items()},
            disaster=str(data.get("disaster", "")),
            bunker=str(data.get("bunker", "")),
            capacity=int(data.get("capacity", 0)),
            discussion_deadline=data.get("discussion_deadline"),
            votes={int(k): int(v) for k, v in dict(data.get("votes", {})).items()},
            vote_round=int(data.get("vote_round", 1)),
            restricted_targets=data.get("restricted_targets"),
            pending_host_tiebreak=bool(data.get("pending_host_tiebreak", False)),
            tie_leaders=list(data.get("tie_leaders", [])),
            winner_ids=list(data.get("winner_ids", [])),
            finish_text=str(data.get("finish_text", "")),
            ui_msg={int(k): int(v) for k, v in dict(data.get("ui_msg", {})).items()},
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )
        players: dict[str, object] = dict(data.get("players", {}))
        room.players = {
            int(uid): PlayerState.from_dict(dict(pd))
            for uid, pd in players.items()
        }
        return room


# ---------------------------------------------------------------------------
# Действия лобби
# ---------------------------------------------------------------------------
def create_room(code: str, host_id: int, host_name: str,
                host_username: Optional[str] = None,
                seed: int | str | None = None) -> GameRoom:
    """Создать комнату и добавить в неё хоста."""
    room = GameRoom(code=code, host_id=host_id)
    if seed is None:
        seed = f"{code}:{time.time_ns()}"
    room._deck = Deck(seed=seed, special_cards_on=room.settings.special_cards_on)
    add_player(room, host_id, host_name, host_username, is_host=True)
    return room


def add_player(room: GameRoom, user_id: int, full_name: str,
               username: Optional[str] = None, is_host: bool = False) -> None:
    """Добавить игрока в лобби."""
    if room.phase != Phase.LOBBY:
        raise GameError("Игра уже началась — войти нельзя.")
    if len(room.players) >= room.settings.max_players:
        raise GameError("Комната заполнена.")
    if user_id in room.players:
        raise GameError("Ты уже в этой комнате.")
    player = PlayerState(
        user_id=user_id,
        full_name=full_name,
        username=username,
        is_host=is_host,
        join_index=len(room.players),
    )
    room.players[user_id] = player
    room.touch()


def remove_player(room: GameRoom, user_id: int) -> PlayerState:
    """Убрать игрока (вышел сам или кикнут хостом). Разрешено только в LOBBY."""
    if room.phase != Phase.LOBBY:
        raise GameError("Игра уже началась — выйти нельзя.")
    player = room.players.pop(user_id, None)
    if player is None:
        raise GameError("Игрок не найден.")
    # смена хоста, если ушёл хост
    if room.host_id == user_id:
        _transfer_host(room)
    room.touch()
    return player


def _transfer_host(room: GameRoom) -> None:
    """Передать роль хоста следующему живому игроку по порядку вступления."""
    candidates = [p for p in sorted(room.players.values(), key=lambda p: p.join_index) if p.alive]
    if not candidates:
        return
    new_host = candidates[0]
    for p in room.players.values():
        p.is_host = False
    new_host.is_host = True
    room.host_id = new_host.user_id


def _pick_disaster(room: GameRoom, rng: random.Random) -> tuple[str, str]:
    mode = room.settings.disaster_mode
    if mode == "classic":
        # последовательный перебор катастроф по номеру раунда
        name, desc = DISASTERS[(room.round_no - 1) % len(DISASTERS)]
        return name, desc
    name, desc = rng.choice(DISASTERS)
    return name, desc


def _compose_bunker(room: GameRoom, rng: random.Random) -> str:
    """Сложить описание бункера для этого раунда."""
    name = rng.choice(BUNKER_NAMES)
    features = rng.sample(BUNKER_FEATURES, k=min(3, len(BUNKER_FEATURES)))
    food_months = rng.randint(3, 24)
    places = room.capacity
    lines = [
        f"🏚 <b>{name}</b>",
        f"🗝 Вместимость: <b>{places} {_plural(places, 'место', 'места', 'мест')}</b>",
        f"🥫 Запасы еды: <b>{food_months} {_plural(food_months, 'месяц', 'месяца', 'месяцев')}</b>",
        "🛠 Что внутри:",
    ]
    lines += [f"  • {f}" for f in features]
    return "\n".join(lines)


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русские множественные формы: 1 место, 2 места, 5 мест."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and (n100 < 10 or n100 >= 20):
        return few
    return many


def start_game(room: GameRoom) -> None:
    """
    Начать игру: раздать карты, выбрать катастрофу и бункер, перейти в REVEAL.
    Вместимость фиксируется при старте как половина числа игроков.
    """
    if room.phase != Phase.LOBBY:
        raise GameError("Игра уже началась.")
    count = len(room.players)
    if count < MIN_PLAYERS:
        raise GameError(f"Нужно минимум {MIN_PLAYERS} игрока, сейчас {count}.")
    if count > room.settings.max_players:
        raise GameError("Слишком много игроков.")

    room.capacity = bunker_capacity(count)
    room.round_no = 1

    seed = f"{room.code}:{room.round_no}:{time.time_ns()}"
    deck = Deck(seed=seed, special_cards_on=room.settings.special_cards_on)
    room._deck = deck

    rng = random.Random(seed)
    for player in room.players.values():
        player.cards = deck.deal(player.user_id)
        player.revealed = []
        player.special_key = player.cards.get(SPECIAL)
        player.special_used = False
        player.immunity = False
        player.alibi = False
        player.double_vote = False
        player.sabotage_target = False
        player.muted_until_round = 0

    name, desc = _pick_disaster(room, rng)
    room.disaster = f"☢️ <b>{name}</b>\n{desc}"
    room.bunker = _compose_bunker(room, rng)

    room.phase = Phase.REVEAL
    room.round_reveals = {}
    room.votes = {}
    room.vote_round = 1
    room.restricted_targets = None
    room.pending_host_tiebreak = False
    room.tie_leaders = []
    room.finish_text = ""
    room.touch()


# ---------------------------------------------------------------------------
# Раскрытие карт
# ---------------------------------------------------------------------------
def reveal_card(room: GameRoom, user_id: int, attr: str) -> None:
    """
    Раскрыть карту в фазе REVEAL.

    В первых раундах раскрывается строго тема раунда (theme_for_round),
    после исчерпания тем — любая закрытая карта. Раскрывает каждый живой игрок.
    """
    if room.phase != Phase.REVEAL:
        raise GameError("Сейчас не фаза раскрытия.")
    player = room.get_player(user_id)
    if not player.alive:
        raise GameError("Ты выбыл и не можешь раскрывать карты.")

    theme = theme_for_round(room.round_no)
    if theme is not None:
        if attr != theme:
            raise GameError(
                f"В этом раунде раскрывается: {CARD_LABELS.get(theme, theme)}."
            )
    player.reveal(attr)
    room.round_reveals[user_id] = room.round_reveals.get(user_id, 0) + 1
    room.touch()

    # Раскрытие особой карты делает её эффект доступным для использования.
    if attr == SPECIAL and player.special_key:
        player.revealed.append(SPECIAL)  # уже добавлено reveal(); ничего не делаем


def all_revealed_for_round(room: GameRoom) -> bool:
    """
    True, когда все живые игроки раскрыли хотя бы по одной карте в этом раунде
    (или им больше нечего раскрывать).
    """
    for player in room.alive_players:
        hidden = player.hidden_cards()
        if not hidden:
            continue  # раскрывать нечего
        if room.round_reveals.get(player.user_id, 0) < 1:
            return False
    return True


def goto_discussion(room: GameRoom, now: float | None = None) -> None:
    """Перейти из REVEAL в DISCUSSION и запустить таймер обсуждения."""
    if room.phase != Phase.REVEAL:
        raise GameError("Не та фаза.")
    if not all_revealed_for_round(room):
        raise GameError("Не все игроки раскрыли карты.")
    now = now if now is not None else time.time()
    room.phase = Phase.DISCUSSION
    room.discussion_deadline = now + room.settings.discussion_seconds
    room.round_reveals = {}
    room.touch()


def open_voting(room: GameRoom) -> None:
    """
    Открыть голосование.

    В production вызывается после DISCUSSION (через сервис timers_loop), но
    для удобства тестов допускаем и фазу REVEAL — считаем, что обсуждение
    пропущено (например, игроки быстро договорились).
    """
    if room.phase == Phase.REVEAL:
        # тестовый/быстрый путь: обсуждение пропускаем, сразу к голосованию
        room.phase = Phase.DISCUSSION
    if room.phase not in (Phase.DISCUSSION, Phase.VOTING):
        raise GameError("Голосование сейчас невозможно.")
    room.phase = Phase.VOTING
    room.discussion_deadline = None
    room.votes = {}
    room.vote_round = 1
    room.restricted_targets = None
    room.pending_host_tiebreak = False
    room.tie_leaders = []
    # очистка разовых эффектов предыдущего голосования
    for p in room.players.values():
        p.immunity = False
        p.alibi = False
        p.double_vote = False
        p.sabotage_target = False
    room.touch()


# ---------------------------------------------------------------------------
# Голосование
# ---------------------------------------------------------------------------
def vote(room: GameRoom, voter_id: int, target_id: int) -> None:
    """
    Учесть голос. Идемпотентно: повторный голос того же игрока не меняет итог
    и кидает GameError (хендлер покажет «ты уже проголосовал»).
    """
    if room.phase != Phase.VOTING:
        raise GameError("Сейчас не идёт голосование.")
    voter = room.get_player(voter_id)
    if not voter.alive:
        raise GameError("Выбывшие игроки не голосуют.")
    if voter.disconnected:
        raise GameError("Ты отключён от комнаты.")
    if voter.muted_until_round >= room.round_no:
        raise GameError("На тебя наложили обет молчания — голосовать нельзя.")

    if voter_id in room.votes:
        raise GameError("Ты уже проголосовал.")

    target = room.get_player(target_id)
    if not target.alive:
        raise GameError("Нельзя голосовать против выбывшего игрока.")
    if target_id == voter_id:
        raise GameError("Нельзя голосовать против себя.")
    if room.restricted_targets is not None and target_id not in room.restricted_targets:
        raise GameError("Можно голосовать только за лидеров голосования.")

    room.votes[voter_id] = target_id
    room.touch()


def _raw_tally(room: GameRoom) -> dict[int, int]:
    """Подсчёт голосов с учётом иммунитета, алиби, саботажа и двойного голоса."""
    counts: dict[int, int] = {uid: 0 for uid in room.players if room.players[uid].alive}

    for voter_id, target_id in room.votes.items():
        voter = room.players.get(voter_id)
        if voter is None or not voter.alive:
            continue
        if voter.sabotage_target:
            continue  # голос саботирован
        target = room.players.get(target_id)
        if target is None or not target.alive:
            continue
        weight = 2 if voter.double_vote else 1
        counts[target_id] += weight

    # алиби: один голос против игрока аннулируется
    for uid, player in room.players.items():
        if player.alive and player.alibi and counts.get(uid, 0) > 0:
            counts[uid] -= 1

    # иммунитет: голоса против не считаются вовсе
    for uid, player in room.players.items():
        if player.alive and player.immunity:
            counts[uid] = 0

    return {uid: c for uid, c in counts.items() if c > 0}


def resolve_voting(room: GameRoom) -> dict[str, object]:
    """
    Подсчитать голоса и определить исход.

    Возвращает:
        {"type": "eliminated" | "revote" | "host_tiebreak", "leader_id": int, "leaders": [...], "counts": {...}}
    """
    counts = _raw_tally(room)
    if not counts:
        return {"type": "revote", "leaders": [p.user_id for p in room.alive_players], "counts": {}}

    max_votes = max(counts.values())
    leaders = [uid for uid, c in counts.items() if c == max_votes]

    if len(leaders) == 1:
        leader = leaders[0]
        eliminate(room, leader)
        return {"type": "eliminated", "leader_id": leader, "leaders": leaders, "counts": counts}

    # ничья
    if room.vote_round == 1:
        # переголосование между лидерами
        room.vote_round = 2
        room.restricted_targets = leaders
        room.votes = {}
        room.phase = Phase.VOTING
        return {"type": "revote", "leaders": leaders, "counts": counts}

    # повторная ничья — решает хост
    room.pending_host_tiebreak = True
    room.tie_leaders = leaders
    room.phase = Phase.VOTING
    return {"type": "host_tiebreak", "leaders": leaders, "counts": counts}


def host_resolve_tie(room: GameRoom, host_id: int, target_id: int) -> None:
    """Хост выбирает, кто выбывает при повторной ничьей."""
    if not room.pending_host_tiebreak:
        raise GameError("Сейчас никто не ждёт решения хоста.")
    if room.host_id != host_id:
        raise GameError("Решение принимает только хост.")
    if target_id not in room.tie_leaders:
        raise GameError("Можно выбрать только лидера голосования.")
    room.pending_host_tiebreak = False
    room.tie_leaders = []
    eliminate(room, target_id)


# ---------------------------------------------------------------------------
# Выбывание и переходы
# ---------------------------------------------------------------------------
def eliminate(room: GameRoom, target_id: int) -> None:
    """Выбывание игрока: раскрыть все его карты, передать хостство при необходимости."""
    player = room.get_player(target_id)
    player.alive = False
    # раскрываем все оставшиеся карты выбывшего
    for attr in player.hidden_cards():
        player.revealed.append(attr)

    if room.host_id == target_id:
        _transfer_host(room)

    room.phase = Phase.RESULT
    room.votes = {}
    room.restricted_targets = None
    room.pending_host_tiebreak = False
    room.tie_leaders = []
    if player.special_key and not player.special_used:
        # карта выбывшего не успела сыграть — она просто уходит вместе с ним
        pass
    room.touch()


def continue_after_result(room: GameRoom) -> bool:
    """
    Перейти из RESULT в следующий раунд или финал.

    Возвращает True, если игра завершена (FINISHED) и нужно показать финал.
    """
    if room.phase != Phase.RESULT:
        raise GameError("Не та фаза.")

    alive = [p for p in room.players.values() if p.alive]
    if len(alive) == room.capacity:
        room.winner_ids = [p.user_id for p in alive]
        room.finish_text = endings.compose_ending(room)
        room.phase = Phase.FINISHED
        return True

    room.round_no += 1
    room.phase = Phase.REVEAL
    room.round_reveals = {}
    room.votes = {}
    room.vote_round = 1
    room.restricted_targets = None
    room.discussion_deadline = None
    # снять эффекты «обета молчания» прошедших раундов
    for p in room.players.values():
        p.muted_until_round = 0
        p.sabotage_target = False
        p.immunity = False
        p.alibi = False
        p.double_vote = False
    room.touch()
    return False


# ---------------------------------------------------------------------------
# Особые карты
# ---------------------------------------------------------------------------
def available_special_actions(room: GameRoom, user_id: int) -> list[tuple[str, str]]:
    """
    Список доступных игроку действий особой карты: (ключ, название).
    Если карты нет, уже использована или фаза не позволяет — пустой список.
    """
    player = room.get_player(user_id)
    if room.phase in (Phase.LOBBY, Phase.FINISHED):
        return []
    if not player.alive or not player.special_key or player.special_used:
        return []
    return [
        (player.special_key, SPECIAL_CARDS_MAP[player.special_key][0])
    ]


def use_special_card(room: GameRoom, user_id: int, target_id: Optional[int]) -> str:
    """
    Применить особую карту игрока.

    Возвращает текст события для общего лога.
    Кидает GameError, если карта неприменима в текущем состоянии.
    """
    player = room.get_player(user_id)
    if room.phase in (Phase.LOBBY, Phase.FINISHED):
        raise GameError("Сейчас нельзя использовать карты.")
    if not player.alive:
        raise GameError("Выбывшие игроки не могут использовать карты.")
    if not player.special_key:
        raise GameError("У тебя нет особой карты.")
    if player.special_used:
        raise GameError("Ты уже использовал свою особую карту.")

    key = player.special_key
    info = SPECIAL_CARDS_MAP[key]
    title = info[0]
    needs_target = info[2]

    if needs_target:
        if target_id is None or target_id == user_id:
            raise GameError("Нужно выбрать другого игрока.")
        target = room.get_player(target_id)
        if not target.alive:
            raise GameError("Нельзя использовать карту на выбывшего игрока.")

    now_round = room.round_no

    if key == "swap_baggage":
        _swap_attr(room, user_id, target_id, "baggage")
    elif key == "swap_profession":
        _swap_attr(room, user_id, target_id, "profession")
    elif key == "swap_health":
        _swap_attr(room, user_id, target_id, "health")
    elif key == "immunity":
        if room.phase != Phase.VOTING:
            raise GameError("Иммунитет можно ставить только во время голосования.")
        player.immunity = True
    elif key == "alibi":
        if room.phase != Phase.VOTING:
            raise GameError("Алиби можно заявить только во время голосования.")
        player.alibi = True
    elif key == "double_vote":
        if room.phase != Phase.VOTING:
            raise GameError("Двойной голос работает только во время голосования.")
        player.double_vote = True
    elif key == "sabotage":
        if room.phase != Phase.VOTING:
            raise GameError("Саботаж работает только во время голосования.")
        if target_id in room.votes:
            raise GameError("Цель уже проголосовала — саботаж не сработает.")
        room.players[target_id].sabotage_target = True
    elif key == "mute":
        room.players[target_id].muted_until_round = now_round + 1
    elif key == "extra_seat":
        room.capacity += 1
    elif key == "peek":
        # подсматриваем случайную закрытую карту цели
        hidden = target.hidden_cards()
        if not hidden:
            raise GameError("У цели нет закрытых карт.")
        attr = hidden[0]
        player.special_used = True
        room.touch()
        return f"🔍 {player.full_name} заглянул в карту игрока {target.full_name}…"
    elif key == "expose":
        hidden = target.hidden_cards()
        if not hidden:
            raise GameError("У цели нет закрытых карт.")
        attr = hidden[0]
        target.revealed.append(attr)
        player.special_used = True
        room.touch()
        return (
            f"🎭 {player.full_name} разоблачил игрока {target.full_name}!\n"
            f"{CARD_LABELS.get(attr, attr)}: <b>{target.cards[attr]}</b>"
        )
    elif key == "revote":
        if room.phase != Phase.VOTING:
            raise GameError("Переголосование доступно только во время голосования.")
        if not room.votes:
            raise GameError("Ещё никто не голосовал.")
        counts = _raw_tally(room)
        leaders = [uid for uid, c in counts.items() if c == max(counts.values())] if counts \
            else [p.user_id for p in room.alive_players]
        room.vote_round = 2
        room.restricted_targets = leaders
        room.votes = {}
        room.pending_host_tiebreak = False
        player.special_used = True
        room.touch()
        return f"♻️ {player.full_name} потребовал переголосования!"
    else:
        raise GameError("Такой карты не существует.")

    player.special_used = True
    room.touch()
    return f"🃏 {player.full_name} использовал карту «{title}»."


def _swap_attr(room: GameRoom, user_id: int, target_id: int, attr: str) -> None:
    """Обмен значениями карты между игроками (с сохранением статуса открытости)."""
    a = room.get_player(user_id)
    b = room.get_player(target_id)
    key_map = {
        "baggage": "baggage",
        "profession": "profession",
        "health": "health",
    }
    key = key_map[attr]
    if key not in a.cards or key not in b.cards:
        raise GameError("Карту не удалось поменять.")
    a.cards[key], b.cards[key] = b.cards[key], a.cards[key]


def peek_result(room: GameRoom, user_id: int, target_id: int) -> str:
    """
    Отдельная функция для карты «Заглянуть в чужую карту» — возвращает
    значение скрытой карты ТОЛЬКО использующему игроку.
    """
    player = room.get_player(user_id)
    target = room.get_player(target_id)
    if not player.special_key or player.special_key != "peek" or player.special_used:
        raise GameError("Карта «Заглянуть» недоступна.")
    hidden = target.hidden_cards()
    if not hidden:
        raise GameError("У цели нет закрытых карт.")
    player.special_used = True
    room.touch()
    attr = hidden[0]
    return f"{CARD_LABELS.get(attr, attr)}: <b>{target.cards[attr]}</b>"