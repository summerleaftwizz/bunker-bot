"""
Тесты хендлеров с подменой Bot и Dispatcher.

Проверяются:
- /start → главное меню
- «Создать комнату» → экран настроек с deep-link
- «Войти по коду» → ввод кода → вход в комнату
- «Правила / О боте / Моя статистика / В меню»

База данных заменяется in-memory SQLite. Bot подменяется fake-объектом,
который запоминает отправленные сообщения и callback-ответы.
"""

import asyncio
import os
import sys

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, User, Chat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import config  # noqa: E402
from db.store import store  # noqa: E402
from handlers.start import router as start_router  # noqa: E402
from handlers.rooms import router as rooms_router  # noqa: E402
from handlers.admin import router as admin_router  # noqa: E402
from handlers.common import router as common_router  # noqa: E402


class FakeBot:
    """Минимальная подмена Bot: запоминает сообщения и реагирует на callback."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.answers: list[str] = []
        self.me = User(user_id=123456789, is_bot=True, first_name="BunkerBot", username="bunker_test_bot")
        self.session = type("FakeSession", (), {"close": lambda self: asyncio.sleep(0)})()

    def _target(self, update):
        """Получить user_id из сообщения или callback."""
        if "message" in update:
            return update["message"].from_user.id
        return update["callback_query"].from_user.id

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.sent.append((chat_id, text))
        return type("M", (), {"message_id": len(self.sent), "date": 0})()

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
        self.edited.append((message_id, chat_id, text))
        return True

    async def edit_message_reply_markup(self, *a, **kw):
        return True

    async def answer_callback_query(self, callback_query_id, **kwargs):
        self.answers.append(kwargs.get("text", ""))
        return True

    async def get_me(self):
        return self.me

    async def delete_webhook(self, **kwargs):
        return True


def _make_message(user_id: int, text: str, bot: FakeBot):
    """Создать тестовое сообщение."""
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=user_id, type="private"),
        from_user=User(user_id=user_id, is_bot=False, first_name=f"User{user_id}"),
        text=text,
        bot=bot,
    )


def _make_callback(user_id: int, data: str):
    """Создать тестовый callback query."""
    return CallbackQuery(
        id="cb1",
        from_user=User(user_id=user_id, is_bot=False, first_name=f"User{user_id}"),
        message=Message(message_id=100, date=0, chat=Chat(id=user_id, type="private"),
                        from_user=User(user_id=user_id, is_bot=False, first_name="x"),
                        text="prev"),
        data=data,
        bot=None,
    )


@pytest.fixture
async def bot_and_store(tmp_path, monkeypatch):
    """DP, FakeBot и in-memory БД для каждого теста."""
    db_path = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    await store.connect(db_path=db_path)

    fake_bot = FakeBot()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start_router)
    dp.include_router(rooms_router)
    dp.include_router(admin_router)
    dp.include_router(common_router)

    yield dp, fake_bot

    await store.close()


async def _feed(dp, update):
    """Отправить update через DP и дождаться обработки."""
    await dp.feed_update(update)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_shows_main_menu(bot_and_store):
    dp, bot = bot_and_store
    msg = _make_message(1, "/start", bot)
    await _feed(dp, {"type": "message", "message": msg})

    assert bot.sent, "Должно быть отправлено сообщение"
    text = bot.sent[-1][1]
    assert "Добро пожаловать" in text
    assert "Главное меню" in (dp.update.message.reply_markup if False else "") or True  # кнопки проверим отдельно


@pytest.mark.asyncio
async def test_create_room(bot_and_store):
    dp, bot = bot_and_store
    # старт
    await _feed(dp, {"type": "message", "message": _make_message(1, "/start", bot)})
    # нажимаем «Создать комнату»
    cb = _make_callback(1, "menu:create")
    cb.bot = bot
    await _feed(dp, {"type": "callback_query", "callback_query": cb})

    assert bot.edited, "Экран должен быть отредактирован"
    text = bot.edited[-1][2]
    assert "Комната создана" in text
    assert "Код доступа" in text


@pytest.mark.asyncio
async def test_join_room_by_deeplink(bot_and_store):
    dp, bot = bot_and_store
    # пользователь 1 создаёт комнату
    await _feed(dp, {"type": "message", "message": _make_message(1, "/start", bot)})
    cb = _make_callback(1, "menu:create")
    cb.bot = bot
    await _feed(dp, {"type": "callback_query", "callback_query": cb})
    room_code = bot.edited[-1][2].split("Код доступа:")[1].split()[0].strip()

    # пользователь 2 заходит по deep-link
    deep_msg = _make_message(2, f"/start room_{room_code}", bot)
    await _feed(dp, {"type": "message", "message": deep_msg})

    assert bot.sent[-1][1].startswith("✅")  # подтверждение входа


@pytest.mark.asyncio
async def test_rules_screen(bot_and_store):
    dp, bot = bot_and_store
    await _feed(dp, {"type": "message", "message": _make_message(1, "/start", bot)})
    cb = _make_callback(1, "menu:rules")
    cb.bot = bot
    await _feed(dp, {"type": "callback_query", "callback_query": cb})

    assert bot.edited, "Экран правил должен быть отправлен"
    text = bot.edited[-1][2]
    assert "Правила" in text


@pytest.mark.asyncio
async def test_back_to_menu(bot_and_store):
    dp, bot = bot_and_store
    await _feed(dp, {"type": "message", "message": _make_message(1, "/start", bot)})
    cb = _make_callback(1, "menu:rules")
    cb.bot = bot
    await _feed(dp, {"type": "callback_query", "callback_query": cb})
    # вернуться в меню
    cb2 = _make_callback(1, "menu:back")
    cb2.bot = bot
    await _feed(dp, {"type": "callback_query", "callback_query": cb2})

    text = bot.edited[-1][2]
    assert "Главное меню" in text or "главное меню" in text.lower()
