"""
Пакет работы с базой данных (aiosqlite).
"""

from .store import Store, store, new_id

__all__ = ["Store", "store", "new_id"]
