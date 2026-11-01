"""
Модуль конфигурации бота.
Загружает параметры из файла .env и предоставляет их в виде объекта Config.
"""

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv


# Загрузка переменных окружения из файла .env
load_dotenv()


@dataclass
class Config:
    """
    Конфигурация бота.
    
    Атрибуты:
        BOT_TOKEN (str): Токен Telegram-бота.
        ADMIN_IDS (List[int]): Список Telegram ID администраторов.
        DB_PATH (str): Путь к базе данных SQLite.
    """
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: List[int] = field(default_factory=list)
    DB_PATH: str = os.getenv("DB_PATH", "sqlite+aiosqlite:///bunker.db")

    def __post_init__(self):
        """Парсинг ADMIN_IDS из строки в список целых чисел."""
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        if admin_ids_str:
            self.ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]


# Создание экземпляра конфигурации для использования в других модулях
config = Config()