"""
Точка входа в Telegram-бота «Бункер».

Запуск: python main.py

Что делает main():
1. Настраивает логирование (файл bot.log + консоль).
2. Загружает конфигурацию (.env) и проверяет BOT_TOKEN.
3. Открывает соединение с SQLite и восстанавливает активные комнаты.
4. Подключает все роутеры и middleware.
5. Запускает фоновые задачи (таймеры обсуждения, авто-очистка).
6. Начинает polling и корректно завершает работу (graceful shutdown).
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from config import config
from db.store import store
from middlewares import ThrottlingMiddleware, DbMiddleware
from services.cleanup import cleanup_loop
from services.recovery import restore_rooms
from services.timers import timers_loop

from handlers.admin import router as admin_router
from handlers.common import router as common_router
from handlers.game import router as game_router
from handlers.rooms import router as rooms_router
from handlers.start import router as start_router
from handlers.voting import router as voting_router

logger = logging.getLogger("main")


def setup_logging() -> None:
    """Логирование: RotatingFileHandler (bot.log) + консоль."""
    formatter = logging.Formatter(
        "%(asctime)s — %(levelname)-8s — %(name)-20s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = logging.handlers.RotatingFileHandler(
        "bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


async def on_startup(dp: Dispatcher, bot: Bot) -> None:
    """Старт: подключение БД, восстановление комнат, фоновые задачи."""
    await store.connect()
    restored = await restore_rooms()
    logger.info("Восстановлено активных комнат: %d", restored)

    dp["timers_task"] = asyncio.create_task(timers_loop(bot))
    dp["cleanup_task"] = asyncio.create_task(cleanup_loop())

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:  # noqa: BLE001
        logger.debug("Вебхук отсутствует — работаем в polling-режиме")


async def on_shutdown(dp: Dispatcher, bot: Bot) -> None:
    """Корректное завершение: остановка фоновых задач и закрытие БД."""
    for key in ("timers_task", "cleanup_task"):
        task = dp.get(key)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await store.close()
    await bot.session.close()
    logger.info("Бот остановлен")


async def main() -> None:
    """Главная функция: настройка и запуск бота."""
    setup_logging()

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не задан в .env! Скопируйте .env.example → .env")
        sys.exit(1)

    logger.info("Инициализация бота…")
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # middleware: антиспам + контекст БД
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.update.middleware(DbMiddleware())

    # роутеры
    dp.include_router(start_router)
    dp.include_router(rooms_router)
    dp.include_router(game_router)
    dp.include_router(voting_router)
    dp.include_router(admin_router)
    dp.include_router(common_router)

    # жизненный цикл
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Бот готов. Запускаю polling…")

    try:
        await dp.start_polling(bot)
    except TelegramNetworkError as exc:
        logger.error("Сетевая ошибка Telegram: %s", exc)
    except Exception:
        logger.exception("Критическая ошибка в polling")
    finally:
        await on_shutdown(dp, bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Остановка бота…")
    except Exception as exc:
        print(f"❌ Ошибка запуска: {exc}")
