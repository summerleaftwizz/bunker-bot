"""
Генерация и раздача карт игрокам.

Все списки берутся из пакета gamedata/. Карты перемешиваются через random.Random
с отдельным зерном на комнату, чтобы результат был детерминированным
и воспроизводимым при рестарте.
"""

from __future__ import annotations

import random
from typing import Optional

from game.state import (
    PROFESSION,
    GENDER_AGE,
    HEALTH,
    HOBBY,
    PHOBIA,
    BAGGAGE,
    FACT,
    SPECIAL,
)

from gamedata.professions import PROFESSIONS
from gamedata.health import HEALTH_STATES
from gamedata.hobbies import HOBBIES
from gamedata.phobias import PHOBIAS
from gamedata.baggages import BAGGAGES
from gamedata.facts import FACTS
from gamedata.special_cards import SPECIAL_CARDS


class Deck:
    """
    Колода, раздающая игрокам карты без повторов внутри одной игры.

    Каждый пул перемешивается один раз при создании комнаты; карты раздаются
    по очереди, поэтому в рамках одной игры одинаковые значения не встречаются.
    """

    def __init__(self, seed: int | str, special_cards_on: bool = True) -> None:
        self._rng = random.Random(seed)
        # Копируем и перемешиваем пулы. Спец-карты раздаём отдельно.
        self._professions = list(PROFESSIONS)
        self._health = list(HEALTH_STATES)
        self._hobbies = list(HOBBIES)
        self._phobias = list(PHOBIAS)
        self._baggages = list(BAGGAGES)
        self._facts = list(FACTS)
        self._special: list[tuple[str, str, str, bool]] = list(SPECIAL_CARDS) if special_cards_on else []

        for pool in (
            self._professions,
            self._health,
            self._hobbies,
            self._phobias,
            self._baggages,
            self._facts,
            self._special,
        ):
            self._rng.shuffle(pool)

        self._special_index = 0

    def draw_profession(self) -> str:
        """Вернуть уникальную профессию."""
        if not self._professions:
            raise RuntimeError("Закончились профессии в колоде")
        return self._professions.pop()

    def draw_health(self) -> str:
        """Вернуть уникальное состояние здоровья."""
        if not self._health:
            raise RuntimeError("Закончились состояния здоровья в колоде")
        return self._health.pop()

    def draw_hobby(self) -> str:
        """Вернуть уникальное хобби."""
        if not self._hobbies:
            raise RuntimeError("Закончились хобби в колоде")
        return self._hobbies.pop()

    def draw_phobia(self) -> str:
        """Вернуть уникальную фобию."""
        if not self._phobias:
            raise RuntimeError("Закончились фобии в колоде")
        return self._phobias.pop()

    def draw_baggage(self) -> str:
        """Вернуть уникальный предмет багажа."""
        if not self._baggages:
            raise RuntimeError("Закончился багаж в колоде")
        return self._baggages.pop()

    def draw_fact(self) -> str:
        """Вернуть уникальный дополнительный факт."""
        if not self._facts:
            raise RuntimeError("Закончились факты в колоде")
        return self._facts.pop()

    def draw_gender_age(self, rng: random.Random | None = None) -> str:
        """
        Сгенерировать строку «пол, возраст».
        Пол и возраст — не список, а генерация, повторы здесь допустимы и не
        нарушают уникальность остальных характеристик.
        """
        rng = rng or self._rng
        gender = rng.choice(["Мужчина", "Женщина"])
        age = rng.randint(18, 75)
        return f"{gender}, {age} лет"

    def draw_special(self) -> Optional[str]:
        """
        Выдать ключ следующей особой карты (или None, если карты выключены
        или закончились).
        """
        if self._special_index >= len(self._special):
            return None
        card = self._special[self._special_index]
        self._special_index += 1
        return card[0]

    def deal(self, player_id: int) -> dict[str, str]:
        """
        Полная раздача карт одному игроку.

        Возвращает словарь: тип карты -> значение. Особая карта (если включена
        и осталась) попадает под ключ SPECIAL.
        """
        cards: dict[str, str] = {
            PROFESSION: self.draw_profession(),
            GENDER_AGE: self.draw_gender_age(),
            HEALTH: self.draw_health(),
            HOBBY: self.draw_hobby(),
            PHOBIA: self.draw_phobia(),
            BAGGAGE: self.draw_baggage(),
            FACT: self.draw_fact(),
        }
        special = self.draw_special()
        if special:
            cards[SPECIAL] = special
        return cards

    def peek_special(self) -> bool:
        """Остались ли особые карты в колоде."""
        return self._special_index < len(self._special)
