"""
Сюжетные концовки бункера.

Концовка зависит от состава выживших: какие навыки у них есть, сколько мест
осталось свободным и какая катастрофа случилась.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - только для типизации
    from game.engine import GameRoom

# Группы навыков: (ключ, подстроки в названии профессии, текст вклада)
SKILL_GROUPS: list[tuple[str, tuple[str, ...], str]] = [
    (
        "medic",
        ("врач", "медик", "фельдшер", "хирург", "санитар", "медсестр", "стоматолог", "ветеринар"),
        "медицинский блок наконец-то работает как надо",
    ),
    (
        "engineer",
        ("инженер", "техник", "механик", "сварщик", "электрик", "сантех", "наладчик", "строител"),
        "системы бункера починены и больше не искрят",
    ),
    (
        "food",
        ("повар", "агроном", "фермер", "садовник", "пекар", "кондитер", "кулинар", "пчеловод"),
        "запасы удалось растянуть и даже разнообразить рацион",
    ),
    (
        "security",
        ("полицей", "военн", "охран", "охотник", "пожарн", "бокс", "спасател"),
        "периметр под контролем, а паника задавлена в зародыше",
    ),
    (
        "science",
        ("учёный", "научн", "биолог", "химик", "физик", "программист", "компьютерщик", "аналитик"),
        "научная группа нашла неожиданное решение проблемы",
    ),
    (
        "morale",
        ("психолог", "учител", "поэт", "писатель", "музыкант", "актёр", "блогер", "библиотекар", "философ"),
        "люди в бункере не сошли с ума — и это дорогого стоит",
    ),
    (
        "hands",
        ("столяр", "плотник", "слесарь", "токар", "кузнец", "швея", "рукодельник", "модельер"),
        "бытовые поломки больше не превращаются в катастрофу",
    ),
]


def _professions_of(room: "GameRoom") -> list[str]:
    """Профессии выживших в нижнем регистре."""
    result = []
    for uid in room.winner_ids:
        player = room.players.get(uid)
        if player and player.cards.get("profession"):
            result.append(player.cards["profession"].lower())
    return result


def _detect_skills(professions: list[str]) -> list[tuple[str, str]]:
    """Найти присутствующие группы навыков."""
    found: list[tuple[str, str]] = []
    for key, keywords, effect in SKILL_GROUPS:
        if any(any(k in prof for k in keywords) for prof in professions):
            found.append((key, effect))
    return found


def compose_ending(room: "GameRoom") -> str:
    """
    Собрать финальный текст: список выживших с картами и «судьба бункера».

    Возвращает готовый HTML-текст.
    """
    survivors = [room.players[uid] for uid in room.winner_ids if uid in room.players]
    professions = _professions_of(room)
    skills = _detect_skills(professions)

    lines: list[str] = []
    lines.append("🏁 <b>Игра окончена</b>")
    lines.append("")
    lines.append(f"🚪 В бункере <b>{len(survivors)}</b> "
                 f"{'место' if len(survivors) == 1 else 'мест'} из {room.capacity}.")
    lines.append("")

    # --- выжившие с картами ---
    lines.append("<b>💚 Выжившие</b>")
    for player in survivors:
        lines.append("")
        lines.append(f"<b>{_esc(player.full_name)}</b>")
        for attr, value in player.cards.items():
            from game.state import CARD_ICONS, CARD_LABELS
            icon = CARD_ICONS.get(attr, "•")
            label = CARD_LABELS.get(attr, attr)
            lines.append(f"{icon} <i>{label}:</i> {_esc(value)}")

    lines.append("")
    lines.append("─" * 18)
    lines.append("<b>📖 Судьба бункера</b>")
    lines.append("")

    ending_notes: list[str] = []

    if not survivors:
        ending_notes.append(
            "Бункер остался пуст. Через несколько недель сюда постучали, "
            "но открывать было некому."
        )
    else:
        extinct_professions = not professions
        if extinct_professions:
            ending_notes.append(
                "Ни у кого из выживших не оказалось профессиональных навыков. "
                "Бункер держался на энтузиазме и изоленте."
            )

        present_keys = {key for key, _ in skills}
        if skills:
            ending_notes.append(
                "Благодаря выжившим " + ", ".join(effect for _, effect in skills) + "."
            )
        missing_core = {"medic", "engineer", "food"} - present_keys
        if not extinct_professions and missing_core:
            gaps = {
                "medic": "некому было лечить болезни",
                "engineer": "техника ломалась и оставалась сломанной",
                "food": "еда кончилась быстрее, чем планировалось",
            }
            ending_notes.append(
                "Но не обошлось без проблем: "
                + "; ".join(gaps[key] for key in sorted(missing_core)) + "."
            )

        # атмосферные концовки
        rng = random.Random(f"{room.code}:{len(survivors)}")
        flavor = [
            "Первые месяцы были тяжёлыми, но выжившие научились называть это нормой.",
            "Из подручных средств получилась приличная община — с календарём и очередью на душ.",
            "Однажды они нашли в бункере старую колоду карт и до конца дней играли в «Бункер».",
            "Когда-нибудь они выйдут наружу. Наверное. Если найдётся тот, кто захочет открыть дверь.",
            "Легенды о том, что творилось в бункере, будут пересказывать ещё долго — с поправками в свою пользу.",
        ]
        ending_notes.append(rng.choice(flavor))

        # особые отметки
        extra_seats = room.capacity - len(survivors)
        if extra_seats >= 2:
            ending_notes.append(
                f"В бункере осталось {extra_seats} свободных "
                f"{'место' if extra_seats == 1 else 'места' if extra_seats < 5 else 'мест'} — "
                "и это повод для споров о том, кого стоило спасти."
            )

        used_cards = [p for p in survivors if p.special_used]
        if used_cards:
            ending_notes.append(
                f"Особые карты пригодились: {len(used_cards)} "
                f"{'игрок' if len(used_cards) == 1 else 'игрока'} "
                "провернули свою маленькую авантюру."
            )

    lines.append("\n".join(ending_notes))

    # --- катастрофа в финале ---
    lines.append("")
    lines.append(f"☢️ <i>Катастрофа:</i> {room.disaster}")

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Экранирование HTML для пользовательских данных."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
