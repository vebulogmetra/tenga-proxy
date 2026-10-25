"""Фасады src.sys отдают одинаковый набор имён на любой ОС."""

from __future__ import annotations

import importlib
import inspect
import sys

import pytest

FACADES = [
    "proxy",
    "vpn",
    "resolver",
    "tun_route",
    "tun_dns",
    "tun_access",
    "single_instance",
]


# Linux-модули тянут fcntl и прочее POSIX-only: на Windows не импортируются.
@pytest.mark.skipif(sys.platform == "win32", reason="Linux implementation")
@pytest.mark.parametrize("name", FACADES)
def test_linux_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    linux = importlib.import_module(f"src.sys.linux.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(linux, attr)]

    assert missing == []


WINDOWS_READY = FACADES


@pytest.mark.parametrize("name", WINDOWS_READY)
def test_windows_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    windows = importlib.import_module(f"src.sys.windows.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(windows, attr)]

    assert missing == []


def _public_params(func) -> list[tuple[str, bool]]:
    """Параметры, которыми пользуется вызывающий код: имя и есть ли default.

    Keyword-only не сравниваются: ими реализации внедряют зависимости для
    тестов (`registry=`, `notify=`), общий код их не передаёт.
    """
    return [
        (p.name, p.default is not inspect.Parameter.empty)
        for p in inspect.signature(func).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
    ]


def _callables(obj) -> dict[str, object]:
    """Функция — она сама; класс — его конструктор и публичные методы."""
    if not inspect.isclass(obj):
        return {"": obj} if callable(obj) else {}
    members = {"__init__": obj.__init__}
    members.update(
        (name, member)
        for name, member in inspect.getmembers(obj, callable)
        if not name.startswith("_")
    )
    return members


# Состояние, которое общий код только хранит и возвращает реализации:
# устройство у каждой ОС своё.
OPAQUE = {"TunRouteState"}


@pytest.mark.skipif(sys.platform == "win32", reason="Linux implementation")
@pytest.mark.parametrize("name", FACADES)
def test_linux_and_windows_signatures_match(name):
    facade = importlib.import_module(f"src.sys.{name}")
    linux = importlib.import_module(f"src.sys.linux.{name}")
    windows = importlib.import_module(f"src.sys.windows.{name}")

    mismatched = []
    for attr in facade.__all__:
        if attr in OPAQUE:
            continue
        linux_value, windows_value = getattr(linux, attr), getattr(windows, attr)
        if not callable(linux_value):
            if linux_value != windows_value:
                mismatched.append(f"{attr}: {linux_value!r} != {windows_value!r}")
            continue
        linux_members = _callables(linux_value)
        windows_members = _callables(windows_value)
        for member in sorted(linux_members.keys() | windows_members.keys()):
            if member not in linux_members or member not in windows_members:
                mismatched.append(f"{attr}.{member}: только в одной реализации")
                continue
            lin = _public_params(linux_members[member])
            win = _public_params(windows_members[member])
            if lin != win:
                mismatched.append(f"{attr}.{member}: linux {lin} != windows {win}")

    assert mismatched == []
