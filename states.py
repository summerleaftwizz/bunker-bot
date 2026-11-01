"""
FSM-состояния для бота.
"""

from aiogram.fsm.state import StatesGroup, State


class Form(StatesGroup):
    """Состояния для ввода кода комнаты."""
    waiting_room_code = State()


__all__ = ["Form"]
