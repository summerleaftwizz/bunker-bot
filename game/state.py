"""
Константы и состояния игрового автомата.

Здесь нет логики — только перечисления, лимиты и словари оформления,
которые используют и движок, и слой Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    """
    Фазы комнаты. Переходы строго контролируются движком:

    LOBBY -> REVEAL -> DISCUSSION -> VOTING -> RESULT -> (REVEAL | FINISHED)
    """

    LOBBY = "lobby"
    REVEAL = "reveal"
    DISCUSSION = "discussion"
    VOTING = "voting"
    RESULT = "result"
    FINISHED = "finished"


# --- Лимиты игроков -------------------------------------------------------
MIN_PLAYERS: int = 4
MAX_PLAYERS: int = 12

# --- Ограничения настроек -------------------------------------------------
MIN_DISCUSSION_SECONDS: int = 30
MAX_DISCUSSION_SECONDS: int = 600
DEFAULT_DISCUSSION_SECONDS: int = 90


# --- Характеристики -------------------------------------------------------
PROFESSION = "profession"
GENDER_AGE = "gender_age"
HEALTH = "health"
HOBBY = "hobby"
PHOBIA = "phobia"
BAGGAGE = "baggage"
FACT = "fact"
SPECIAL = "special"

# Порядок карт в «карточке игрока» (и порядок раскрытия по раундам).
REVEAL_THEMES: tuple[str, ...] = (
    PROFESSION,
    GENDER_AGE,
    HEALTH,
    HOBBY,
    PHOBIA,
    BAGGAGE,
    FACT,
)

CARD_ICONS: dict[str, str] = {
    PROFESSION: "👷",
    GENDER_AGE: "🧬",
    HEALTH: "❤️",
    HOBBY: "🎯",
    PHOBIA: "😱",
    BAGGAGE: "🎒",
    FACT: "📌",
    SPECIAL: "🃏",
}

CARD_LABELS: dict[str, str] = {
    PROFESSION: "Профессия",
    GENDER_AGE: "Пол и возраст",
    HEALTH: "Состояние здоровья",
    HOBBY: "Хобби",
    PHOBIA: "Фобия",
    BAGGAGE: "Багаж",
    FACT: "Доп. факт",
    SPECIAL: "Особая карта",
}


def theme_for_round(round_no: int) -> str | None:
    """
    Тема раскрытия для раунда.

    Первый раунд — профессия, дальше по порядку REVEAL_THEMES.
    Когда темы заканчиваются — игрок раскрывает любую оставшуюся карту (None).
    """
    index = round_no - 1
    if 0 <= index < len(REVEAL_THEMES):
        return REVEAL_THEMES[index]
    return None


def bunker_capacity(players_count: int) -> int:
    """
    Вместимость бункера: половина игроков, округление вниз, но не меньше 1.
    """
    return max(1, players_count // 2)


@dataclass
class RoomSettings:
    """
    Настройки комнаты, которые может менять хост.

    Атрибуты:
        discussion_seconds: длительность обсуждения в секундах.
        max_players: максимальное число игроков (4–12).
        special_cards_on: раздавать ли особые карты.
        disaster_mode: режим катастроф ("random" — случайные, "classic" — последовательные).
    """

    discussion_seconds: int = DEFAULT_DISCUSSION_SECONDS
    max_players: int = MAX_PLAYERS
    special_cards_on: bool = True
    disaster_mode: str = "random"

    def clamp(self) -> "RoomSettings":
        """Приводит значения к допустимым границам (защита от подделки данных)."""
        self.discussion_seconds = min(
            MAX_DISCUSSION_SECONDS, max(MIN_DISCUSSION_SECONDS, int(self.discussion_seconds))
        )
        self.max_players = min(MAX_PLAYERS, max(MIN_PLAYERS, int(self.max_players)))
        if self.disaster_mode not in ("random", "classic"):
            self.disaster_mode = "random"
        self.special_cards_on = bool(self.special_cards_on)
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "discussion_seconds": self.discussion_seconds,
            "max_players": self.max_players,
            "special_cards_on": self.special_cards_on,
            "disaster_mode": self.disaster_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RoomSettings":
        return cls(
            discussion_seconds=int(data.get("discussion_seconds", DEFAULT_DISCUSSION_SECONDS)),
            max_players=int(data.get("max_players", MAX_PLAYERS)),
            special_cards_on=bool(data.get("special_cards_on", True)),
            disaster_mode=str(data.get("disaster_mode", "random")),
        ).clamp()
