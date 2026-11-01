"""
Аудит соответствия callback_data (кнопки) и фильтров обработчиков.

Собирает все callback_data, которые могут сгенерировать клавиатуры, и все
шаблоны F.data() в хендлерах, после чего проверяет, что каждая кнопка
покрыта обработчиком, а каждый шаблон достижим хотя бы одной кнопкой.

Запуск:  python tests/check_callbacks.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEYBOARDS = os.path.join(ROOT, "keyboards")
HANDLERS = os.path.join(ROOT, "handlers")

# callback_data, формируемые динамически (f-строки с uid/attr)
DYNAMIC_TEMPLATES = {
    r"lobby:kick": r"^lobby:kick:\d+$",
    r"reveal:": r"^reveal:[a-z_]+$",
    r"sp:target": r"^sp:target:\d+$",
    r"vote:": r"^vote:\d+$",
    r"tb:": r"^tb:\d+$",
}


_BTN = re.compile(r'_btn\(\s*f?["\']([^"\']*)["\']\s*,\s*f?["\']([^"\']*)["\']\s*\)')


def collect_static_callbacks() -> set[str]:
    """Все литеральные callback_data (callback_data=... и _btn)."""
    found: set[str] = set()
    pat = re.compile(r'callback_data\s*=\s*f?["\']([^"\{]+)["\']')
    for fname in os.listdir(KEYBOARDS):
        if not fname.endswith(".py"):
            continue
        src = open(os.path.join(KEYBOARDS, fname), encoding="utf-8").read()
        found.update(pat.findall(src))
        for _text, data in _BTN.findall(src):
            if "{" not in data:
                found.add(data)
    return found


def collect_dynamic_prefixes() -> set[str]:
    """Префиксы динамических callback_data (f-строки)."""
    prefixes: set[str] = set()
    for fname in os.listdir(KEYBOARDS):
        if not fname.endswith(".py"):
            continue
        src = open(os.path.join(KEYBOARDS, fname), encoding="utf-8").read()
        # f"...{uid}" внутри _btn
        for m in re.finditer(r'_btn\(\s*f?["\'].*?["\']\s*,\s*f["\']([^"\{]+)\{', src):
            prefixes.add(m.group(1))
        # InlineKeyboardButton(..., callback_data=f"...{uid}")
        for m in re.finditer(r'callback_data\s*=\s*f["\']([^"\{]+)\{', src):
            prefixes.add(m.group(1))
    return prefixes


def collect_filters() -> set[str]:
    """Все F.data == / F.data.startswith / F.data.regexp шаблоны в хендлерах."""
    patterns: set[str] = set()
    for fname in os.listdir(HANDLERS):
        if not fname.endswith(".py"):
            continue
        src = open(os.path.join(HANDLERS, fname), encoding="utf-8").read()
        patterns.update(re.findall(r'F\.data\s*==\s*["\']([^"\']+)["\']', src))
        patterns.update(re.findall(r'F\.data\.startswith\(["\']([^"\']+)["\']\)', src))
        patterns.update(re.findall(r'F\.data\.regexp\(r?["\']([^"\']+)["\']\)', src))
    return patterns


def main() -> int:
    static = collect_static_callbacks()
    dyn_prefixes = collect_dynamic_prefixes()
    filters = collect_filters()

    print("=== Кнопки без обработчика ===")
    uncovered = []
    for cb in sorted(static):
        if any(cb == f or f in cb or cb.startswith(f) for f in filters):
            continue
        uncovered.append(cb)
        print("  MISSING:", cb)

    print("=== Динамические кнопки без обработчика ===")
    for prefix in sorted(dyn_prefixes):
        if any(prefix.startswith(f) for f in filters):
            continue
        uncovered.append(prefix + "*")
        print("  MISSING:", prefix + "*")

    print("=== Шаблоны-фильтры без кнопок (только предупреждение) ===")
    for f in sorted(filters):
        known = False
        for cb in list(static) + list(dyn_prefixes):
            if cb == f or cb.startswith(f) or f in cb:
                known = True
                break
        if not known:
            print("  WARN (нет кнопки):", f)

    total_missing = len(uncovered)
    print()
    print(f"Кнопок статических: {len(static)}, динамических: {len(dyn_prefixes)}, "
          f"фильтров: {len(filters)}, не покрыто: {total_missing}")
    return 1 if total_missing else 0


if __name__ == "__main__":
    sys.exit(main())
