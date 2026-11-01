"""
Генерация PNG-карточки игрока (Pillow).

Карточка — «досье» жителя бункера: имя, профессия, здоровье, хобби, фобия,
багаж и факт. Используется кнопкой «Мои карты».

Если Pillow не установлен, `render_player_card` возвращает None, и вызывающий
код просто отправляет текст — бот продолжает работать.
"""

from __future__ import annotations

import logging
import os
import textwrap
from typing import Optional

from game.state import (
    BAGGAGE,
    FACT,
    GENDER_AGE,
    HEALTH,
    HOBBY,
    PHOBIA,
    PROFESSION,
)

logger = logging.getLogger(__name__)

# Узбекский стиль: тёмный бункер + янтарные акценты
_BG_TOP = (18, 20, 26)
_BG_BOTTOM = (34, 30, 26)
_ACCENT = (232, 168, 74)
_TEXT = (232, 230, 224)
_DIM = (150, 146, 138)
_CARD_BG = (28, 30, 38)
_CARD_EDGE = (58, 54, 46)

_ROWS = [
    (PROFESSION, "Профессия"),
    (GENDER_AGE, "Пол и возраст"),
    (HEALTH, "Здоровье"),
    (HOBBY, "Хобби"),
    (PHOBIA, "Фобия"),
    (BAGGAGE, "Багаж"),
    (FACT, "Факт"),
]

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)

_FONT_BOLD_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _load_font(size: int, bold: bool = False):
    """Подобрать доступный шрифт; вернуть None, если ничего не нашлось."""
    from PIL import ImageFont  # локальный импорт: не падать без Pillow

    candidates = _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def _wrap(text: str, width: int) -> list[str]:
    """Перенос длинного значения карты на несколько строк."""
    if not text:
        return [""]
    return textwrap.wrap(text, width=width) or [""]


def render_player_card(player, room_code: str = "") -> Optional[bytes]:
    """
    Нарисовать карточку игрока и вернуть PNG в байтах.

    Возвращает None, если Pillow недоступен или произошла ошибка отрисовки.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001 - Pillow может отсутствовать
        logger.warning("Pillow не установлен — отправляю карты текстом")
        return None

    try:
        width = 900
        padding = 34
        line_height = 26
        title_font = _load_font(38, bold=True)
        sub_font = _load_font(22)
        label_font = _load_font(20, bold=True)
        value_font = _load_font(23)

        # --- считаем высоту заранее ---
        blocks: list[tuple[str, str, list[str]]] = []
        for attr, label in _ROWS:
            value = str(player.cards.get(attr, "—") or "—")
            blocks.append((attr, label, _wrap(value, 46)))

        body_height = sum(len(lines) * line_height + 16 for _, _, lines in blocks)
        height = padding * 2 + 120 + body_height + 60

        image = Image.new("RGB", (width, height), _BG_TOP)
        draw = ImageDraw.Draw(image)

        # градиентный фон
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = tuple(
                int(_BG_TOP[i] + (_BG_BOTTOM[i] - _BG_TOP[i]) * ratio) for i in range(3)
            )
            draw.line([(0, y), (width, y)], fill=color)

        # рамка и заголовок
        draw.rounded_rectangle(
            [10, 10, width - 10, height - 10], radius=18, outline=_CARD_EDGE, width=3
        )
        draw.text((padding, padding), "ДОСЬЕ ЖИТЕЛЯ БУНКЕРА", font=title_font, fill=_ACCENT)

        subtitle = f"Игрок: {player.full_name}"
        if room_code:
            subtitle += f"   ·   комната {room_code}"
        draw.text((padding, padding + 52), subtitle, font=sub_font, fill=_DIM)

        # карточки строк
        y = padding + 120
        card_left, card_right = padding, width - padding
        for _, label, lines in blocks:
            block_height = len(lines) * line_height + 16
            draw.rounded_rectangle(
                [card_left, y, card_right, y + block_height],
                radius=10,
                fill=_CARD_BG,
                outline=_CARD_EDGE,
            )
            draw.text((card_left + 16, y + 8), label.upper(), font=label_font, fill=_ACCENT)
            text_y = y + 8
            for line in lines:
                draw.text(
                    (card_left + 170, text_y),
                    line,
                    font=value_font,
                    fill=_TEXT,
                )
                text_y += line_height
            y += block_height + 6

        # подпись
        if player.special_key and not player.special_used:
            draw.text(
                (padding, height - padding - 22),
                "Есть особая карта — используй её с умом.",
                font=sub_font,
                fill=_DIM,
            )

        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - картинка не должна ронять игру
        logger.exception("Не удалось отрисовать карточку игрока")
        return None
