"""
Автономный запуск тестов движка без обязательного pytest.

Использование (из папки bunker_bot):
    python tests/run_tests.py

Если pytest установлен — используется он. Если нет — подставляется
минимальная заглушка (raises), и все тесты из tests/test_engine.py
выполняются напрямую. Это позволяет проверять логику на чистом Python.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import pathlib
import sys
import traceback
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _install_pytest_stub() -> bool:
    """Поставить заглушку pytest, если его нет. Вернуть True, если заглушка нужна."""
    try:
        import pytest  # noqa: F401
        return False
    except ImportError:
        pass

    stub = types.ModuleType("pytest")

    @contextlib.contextmanager
    def raises(expected_exception):
        try:
            yield
        except expected_exception:
            return
        raise AssertionError(f"Ожидалось исключение {expected_exception.__name__}")

    class _Mark:
        @staticmethod
        def asyncio(func):
            return func

    stub.raises = raises
    stub.mark = _Mark()
    stub.main = lambda *args, **kwargs: 0
    sys.modules["pytest"] = stub
    return True


def main() -> int:
    """Запустить все тесты из test_engine.py и вернуть код выхода."""
    stubbed = _install_pytest_stub()
    print("pytest не найден — используется встроенная заглушка\n" if stubbed else "pytest найден\n")

    from tests import test_engine

    tests = [
        (name, obj)
        for name, obj in vars(test_engine).items()
        if name.startswith("test_") and callable(obj)
    ]
    tests.sort(key=lambda pair: pair[0])

    passed = failed = skipped = 0
    failures: list[tuple[str, str]] = []

    for name, func in tests:
        if inspect.iscoroutinefunction(func):
            try:
                asyncio.run(func())
            except Exception:  # noqa: BLE001
                failed += 1
                failures.append((name, traceback.format_exc()))
            else:
                passed += 1
            continue
        try:
            func()
        except AssertionError as exc:
            failed += 1
            failures.append((name, str(exc) or "assert failed"))
        except Exception:  # noqa: BLE001
            failed += 1
            failures.append((name, traceback.format_exc()))
        else:
            passed += 1

    for name, err in failures:
        print(f"FAIL  {name}\n{err}\n")

    print(f"Итого: {passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())