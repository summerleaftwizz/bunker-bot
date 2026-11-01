"""
Тесты игрового движка (без Telegram — чистый Python).

Запуск: pytest tests/ -v      (если pytest установлен)
       python tests/run_tests.py  (встроенный runner)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import pytest
from game import engine as eng
from game.state import Phase, theme_for_round


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
def make_room(code: str = "ABCD123"):
    """Создать тестовую комнату с одним игроком-хостом."""
    return eng.create_room(code=code, host_id=1, host_name="Host", host_username="host")


def add_bot(room):
    """Добавить 4 бота → всего 5 игроков с хостом."""
    for i in range(2, 6):
        eng.add_player(room, user_id=i, full_name=f"Bot{i}", username=f"bot{i}")


def start_and_get_room():
    """Создать комнату, добавить ботов, начать игру."""
    room = make_room()
    add_bot(room)
    eng.start_game(room)
    return room


def vote_all_for(room, target_id: int):
    """Все живые игроки (кроме target) голосуют против target_id."""
    for voter_id, p in room.players.items():
        if not p.alive or voter_id == target_id:
            continue
        eng.vote(room, voter_id, target_id)


# ---------------------------------------------------------------------------
# Создание и вход
# ---------------------------------------------------------------------------
def test_create_room_creates_host():
    room = make_room()
    assert room.phase == Phase.LOBBY
    assert room.host_id == 1
    assert len(room.players) == 1
    assert room.players[1].is_host


def test_add_player_success():
    room = make_room()
    eng.add_player(room, 2, "P2", None)
    assert 2 in room.players and len(room.players) == 2


def test_add_player_duplicate_fails():
    room = make_room()
    with pytest.raises(eng.GameError):
        eng.add_player(room, 1, "Dup", None)


def test_add_player_when_game_started_fails():
    room = start_and_get_room()
    with pytest.raises(eng.GameError):
        eng.add_player(room, 99, "Late", None)


def test_remove_player_transfers_host():
    room = make_room()
    eng.add_player(room, 2, "P2", None)
    eng.remove_player(room, 1)
    assert 2 in room.players and room.players[2].is_host
    assert room.host_id == 2


# ---------------------------------------------------------------------------
# Старт игры
# ---------------------------------------------------------------------------
def test_start_game_min_players():
    room = make_room()
    eng.add_player(room, 2, "P2", None)
    with pytest.raises(eng.GameError):
        eng.start_game(room)


def test_start_game_distributes_cards():
    room = start_and_get_room()
    assert room.phase == Phase.REVEAL
    for player in room.players.values():
        for attr in ("profession", "health", "hobby", "phobia", "baggage", "fact", "gender_age"):
            assert attr in player.cards


def test_start_game_capacity():
    room = start_and_get_room()
    assert room.capacity == 2  # 5 игроков → 2 места


def test_start_game_disaster_and_bunker():
    room = start_and_get_room()
    assert room.disaster != "" and len(room.bunker) > 0


# ---------------------------------------------------------------------------
# Раскрытие карт
# ---------------------------------------------------------------------------
def test_reveal_correct_theme():
    room = start_and_get_room()
    player = room.players[1]
    eng.reveal_card(room, 1, "profession")
    assert "profession" in player.revealed and room.round_reveals[1] == 1


def test_reveal_wrong_theme_fails():
    room = start_and_get_room()
    with pytest.raises(eng.GameError):
        eng.reveal_card(room, 1, "health")


def test_reveal_already_open_fails():
    room = start_and_get_room()
    eng.reveal_card(room, 1, "profession")
    with pytest.raises(eng.GameError):
        eng.reveal_card(room, 1, "profession")


def test_reveal_after_voting_fails():
    room = start_and_get_room()
    eng.open_voting(room)
    with pytest.raises(eng.GameError):
        eng.reveal_card(room, 1, "profession")


# ---------------------------------------------------------------------------
# Голосование
# ---------------------------------------------------------------------------
def _setup_voting(room):
    eng.open_voting(room)
    assert room.phase == Phase.VOTING


def test_vote_success():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    assert room.votes[1] == 2


def test_vote_cannot_vote_self():
    room = start_and_get_room()
    _setup_voting(room)
    with pytest.raises(eng.GameError):
        eng.vote(room, 1, 1)


def test_vote_cannot_vote_twice():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    with pytest.raises(eng.GameError):
        eng.vote(room, 1, 3)


def test_vote_dead_player_fails():
    room = start_and_get_room()
    eng.eliminate(room, 3)
    eng.continue_after_result(room)
    eng.open_voting(room)
    with pytest.raises(eng.GameError):
        eng.vote(room, 1, 3)


def test_eliminate_removes_player():
    room = start_and_get_room()
    _setup_voting(room)
    vote_all_for(room, 2)
    result = eng.resolve_voting(room)
    assert result["type"] == "eliminated" and not room.players[2].alive


def test_resolve_tie_triggers_revote():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    eng.vote(room, 3, 2)
    eng.vote(room, 4, 3)
    eng.vote(room, 5, 3)
    result = eng.resolve_voting(room)
    assert result["type"] == "revote" and set(result["leaders"]) == {2, 3}


def test_host_resolves_tiebreak():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    eng.vote(room, 3, 2)
    eng.vote(room, 4, 3)
    eng.vote(room, 5, 3)
    eng.resolve_voting(room)  # revote между 2 и 3

    # вторая ничья: снова 2:2 между лидерами 2 и 3
    eng.vote(room, 1, 2)
    eng.vote(room, 3, 2)
    eng.vote(room, 4, 3)
    eng.vote(room, 5, 3)
    result = eng.resolve_voting(room)
    assert result["type"] == "host_tiebreak"
    assert set(result["leaders"]) == {2, 3}

    eng.host_resolve_tie(room, 1, 2)
    assert not room.players[2].alive


# ---------------------------------------------------------------------------
# Спецкарты
# ---------------------------------------------------------------------------
def test_use_immunity_card():
    room = start_and_get_room()
    _setup_voting(room)  # immunity работает только во время голосования
    p = room.players[1]
    p.special_key, p.special_used = "immunity", False
    eng.use_special_card(room, 1, None)
    assert p.special_used and p.immunity


def test_use_swap_health_card():
    room = start_and_get_room()
    p = room.players[1]
    target = room.players[2]
    mine, theirs = p.cards["health"], target.cards["health"]
    p.special_key, p.special_used = "swap_health", False
    eng.use_special_card(room, 1, 2)  # требует цель
    assert p.cards["health"] == theirs
    assert target.cards["health"] == mine


def test_use_swap_baggage_card():
    room = start_and_get_room()
    p = room.players[1]
    target = room.players[2]
    mine, theirs = p.cards["baggage"], target.cards["baggage"]
    p.special_key, p.special_used = "swap_baggage", False
    eng.use_special_card(room, 1, 2)
    assert p.cards["baggage"] == theirs
    assert target.cards["baggage"] == mine


def test_use_swap_profession_card():
    room = start_and_get_room()
    p = room.players[1]
    target = room.players[2]
    mine, theirs = p.cards["profession"], target.cards["profession"]
    p.special_key, p.special_used = "swap_profession", False
    eng.use_special_card(room, 1, 2)
    assert p.cards["profession"] == theirs
    assert target.cards["profession"] == mine


def test_use_double_vote_affects_tally():
    room = start_and_get_room()
    _setup_voting(room)  # double_vote работает только во время голосования
    p = room.players[1]
    p.special_key, p.special_used = "double_vote", False
    eng.use_special_card(room, 1, None)
    eng.vote(room, 1, 2)
    assert eng._raw_tally(room)[2] == 2


def test_use_mute_card():
    room = start_and_get_room()
    p = room.players[1]
    p.special_key, p.special_used = "mute", False
    eng.use_special_card(room, 1, 2)
    assert room.players[2].muted_until_round == room.round_no + 1


def test_use_extra_seat_card():
    room = start_and_get_room()
    p = room.players[1]
    original = room.capacity
    p.special_key, p.special_used = "extra_seat", False
    eng.use_special_card(room, 1, None)
    assert room.capacity == original + 1


def test_use_alibi_card():
    room = start_and_get_room()
    _setup_voting(room)  # alibi работает только во время голосования
    p = room.players[1]
    p.special_key, p.special_used = "alibi", False
    eng.use_special_card(room, 1, None)
    assert p.alibi


def test_use_expose_card_reveals_target():
    room = start_and_get_room()
    p = room.players[1]
    target = room.players[2]
    eng.reveal_card(room, 2, "profession")
    p.special_key, p.special_used = "expose", False
    result = eng.use_special_card(room, 1, 2)
    assert "разоблачил" in result.lower()
    assert "profession" in target.revealed


def test_use_peek_card():
    room = start_and_get_room()
    p = room.players[1]
    p.special_key, p.special_used = "peek", False
    result = eng.use_special_card(room, 1, 2)
    assert "заглянул" in result


def test_use_sabotage_card():
    room = start_and_get_room()
    _setup_voting(room)  # sabotage работает только во время голосования
    p = room.players[1]
    p.special_key, p.special_used = "sabotage", False
    # чтобы sabotage сработал, цель (игрок 2) ещё не должна проголосовать
    eng.vote(room, 3, 4)  # кто-то другой голосует не за 2
    eng.use_special_card(room, 1, 2)
    assert room.players[2].sabotage_target


def test_use_revote_card_requires_voting():
    room = start_and_get_room()
    p = room.players[1]
    p.special_key, p.special_used = "revote", False
    with pytest.raises(eng.GameError):
        eng.use_special_card(room, 1, None)


def test_use_revote_card_in_voting():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    eng.vote(room, 3, 2)
    eng.vote(room, 4, 3)
    eng.vote(room, 5, 3)
    p = room.players[1]
    p.special_key, p.special_used = "revote", False
    result = eng.use_special_card(room, 1, None)
    assert "переголосован" in result.lower()
    assert room.vote_round == 2
    assert set(room.restricted_targets) == {2, 3}


# ---------------------------------------------------------------------------
# Сериализация
# ---------------------------------------------------------------------------
def test_serialization_roundtrip():
    room = start_and_get_room()
    eng.reveal_card(room, 1, "profession")
    eng.reveal_card(room, 2, "profession")
    eng.open_voting(room)
    eng.vote(room, 1, 2)

    restored = eng.GameRoom.from_dict(room.to_dict())
    assert restored.code == room.code
    assert restored.phase == room.phase
    assert restored.votes == room.votes
    assert restored.players[1].revealed == room.players[1].revealed
    assert restored.players[2].cards == room.players[2].cards


# ---------------------------------------------------------------------------
# Финал и завершение
# ---------------------------------------------------------------------------
def test_game_finishes_when_capacity_reached():
    room = start_and_get_room()
    # раунд 1: выбываем 5
    _setup_voting(room)
    vote_all_for(room, 5)
    eng.resolve_voting(room)
    assert room.phase == Phase.RESULT
    assert eng.continue_after_result(room) is False
    assert room.round_no == 2

    # раунд 2: выбываем 4
    eng.open_voting(room)
    vote_all_for(room, 4)
    eng.resolve_voting(room)
    assert eng.continue_after_result(room) is False

    # раунд 3: выбываем 3 → живы 1,2 = capacity → конец
    eng.open_voting(room)
    vote_all_for(room, 3)
    eng.resolve_voting(room)
    assert eng.continue_after_result(room) is True
    assert room.phase == Phase.FINISHED
    assert set(room.winner_ids) == {1, 2}


def test_deck_draws_unique():
    room = start_and_get_room()
    pros = [p.cards["profession"] for p in room.players.values()]
    assert len(pros) == len(set(pros))


def test_get_player_not_in_room():
    room = make_room()
    with pytest.raises(eng.GameError):
        room.get_player(999)


def test_all_revealed_for_round():
    room = start_and_get_room()
    assert not eng.all_revealed_for_round(room)
    for uid in room.players:
        eng.reveal_card(room, uid, "profession")
    assert eng.all_revealed_for_round(room)


def test_theme_progression():
    assert theme_for_round(1) == "profession"
    assert theme_for_round(2) == "gender_age"
    assert theme_for_round(3) == "health"
    assert theme_for_round(4) == "hobby"
    assert theme_for_round(5) == "phobia"
    assert theme_for_round(6) == "baggage"
    assert theme_for_round(7) == "fact"
    assert theme_for_round(8) is None  # свободный выбор


def test_eliminate_cleans_voting_state():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    eng.eliminate(room, 2)
    assert room.phase == Phase.RESULT and not room.players[2].alive


def test_vote_in_revote_only_leaders():
    room = start_and_get_room()
    _setup_voting(room)
    eng.vote(room, 1, 2)
    eng.vote(room, 3, 2)
    eng.vote(room, 4, 3)
    eng.vote(room, 5, 3)
    eng.resolve_voting(room)  # revote между 2 и 3
    # попытка проголосовать за НЕ-лидера
    with pytest.raises(eng.GameError):
        eng.vote(room, 1, 4)
    # можно за лидера
    eng.vote(room, 1, 2)
    assert room.votes[1] == 2


def test_mute_prevents_voting():
    room = start_and_get_room()
    _setup_voting(room)
    room.players[3].muted_until_round = room.round_no
    with pytest.raises(eng.GameError):
        eng.vote(room, 3, 2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])