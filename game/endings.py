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


# ---------------------------------------------------------------------------
# Сюжетный финал: мини-рассказ о первых месяцах в бункере
# ---------------------------------------------------------------------------
# Ключ навыка -> как этот человек меняет жизнь бункера (фраза-вклад)
_STORY_CONTRIBUTIONS: dict[str, str] = {
    "medic": "лечил раны и однажды вытащил с того света сразу двоих",
    "engineer": "чинил генератор по ночам и научил остальных не бояться проводов",
    "food": "умудрялся готовить что-то съедобное даже из последних банок",
    "security": "обходил периметр дважды в сутки и не пропускал ни одного шороха",
    "science": "вёл записи, благодаря которым бункер перестал работать наугад",
    "morale": "рассказывал истории, когда все уже были готовы сдаться",
    "hands": "превращал сломанные вещи в нужные — от полки до водяного фильтра",
}

# Атмосферные зачины, зависящие от числа выживших
_STORY_OPENINGS: dict[int, str] = {
    0: "Дверь бункера закрылась, и снаружи не осталось никого, кто мог бы её открыть.",
    1: "В бункере остался один человек — и тишина, слишком громкая даже для подземелья.",
}

_STORY_MIDDLE = [
    "Первые недели прошли в спорах о том, кто прав, и в тихой радости, что дверь выдержала.",
    "Поначалу все вздрагивали от каждого звука снаружи, потом привыкли — и это оказалось страшнее.",
    "Они делили пайки по часам, а по вечерам считали дни до конца запасов.",
]

_STORY_ENDINGS = [
    "Когда-нибудь они выйдут наружу — если найдут в себе силы открыть дверь.",
    "Внизу уже почти получилась община: с календарём, очередью на душ и своим фольклором.",
    "Легенды об этих месяцах будут пересказывать ещё долго, каждый раз с новыми подробностями.",
]


def compose_story(room: "GameRoom") -> str:
    """
    Мини-рассказ о том, как сложилась жизнь в бункере.

    Зависит от профессий выживших: врач, инженер, повар и прочие навыки
    меняют судьбу убежища. Возвращает HTML-текст.
    """
    survivors = [room.players[uid] for uid in room.winner_ids if uid in room.players]

    if not survivors:
        return (
            "📖 <b>Эпилог</b>\n\n"
            "Бункер остался пуст. Через несколько недель снаружи постучали, "
            "но открывать было некому — и стук стих."
        )

    professions = _professions_of(room)
    skills = _detect_skills(professions)
    rng = random.Random(f"{room.code}:story:{len(survivors)}")

    names = ", ".join(_esc(p.full_name) for p in survivors)
    parts: list[str] = ["📖 <b>Эпилог</b>", ""]

    opening = _STORY_OPENINGS.get(len(survivors))
    if opening:
        parts.append(opening)
    else:
        parts.append(
            f"Дверь бункера закрылась за спинами {len(survivors)} "
            f"{'человека' if len(survivors) < 5 else 'человек'}."
        )

    parts.append(rng.choice(_STORY_MIDDLE))

    if skills:
        contribs: list[str] = []
        for key, effect in skills:
            keywords = next(kws for k, kws, _ in SKILL_GROUPS if k == key)
            for p in survivors:
                prof = p.cards.get("profession", "").lower()
                if any(kw in prof for kw in keywords):
                    contribs.append(
                        f"{_esc(p.full_name)} {_STORY_CONTRIBUTIONS.get(key, effect)}"
                    )
        if contribs:
            parts.append(
                "Особенно запомнились те, кто взял на себя главное: "
                + "; ".join(contribs[:4]) + "."
            )

        missing = {"medic", "engineer", "food"} - {key for key, _ in skills}
        if missing:
            gaps = {
                "medic": "болезни лечили народными методами, и не всегда удачно",
                "engineer": "вода и свет держались на честном слове",
                "food": "запасы таяли быстрее, чем хотелось бы",
            }
            parts.append(
                "Но были и потери: "
                + "; ".join(gaps[key] for key in sorted(missing)) + "."
            )
    else:
        parts.append(
            "Профессий у выживших почти не было — бункер держался на изоленте, "
            "упрямстве и умении договариваться."
        )

    parts.append("")
    parts.append(f"<i>Те, кто остался снаружи: {names}.</i>")
    parts.append(rng.choice(_STORY_ENDINGS))

    return "\n".join(parts)
