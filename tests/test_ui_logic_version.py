from __future__ import annotations

import src
from src.ui.logic.version import UNKNOWN, app_version, core_version


def test_app_version_comes_from_the_package_itself(monkeypatch):
    """Версия читается из исходников, а не у установленного пакета.

    В AppImage пакет через pip не ставится, метаданных нет — а версию
    показывать надо, и она там как раз самая нужная.
    """
    monkeypatch.setattr(src, "__version__", "1.2.3")

    assert app_version() == "1.2.3"


def test_app_version_falls_back_to_a_dash(monkeypatch):
    """Совсем без версии показывается прочерк, а не пустое место."""
    monkeypatch.delattr(src, "__version__", raising=False)

    assert app_version() == UNKNOWN


def test_core_version_reports_what_the_core_says():
    """Версия ядра берётся у самого ядра."""
    manager = type("Manager", (), {"get_version": lambda _self: {"version": "26.3.27"}})()

    assert core_version(manager) == "26.3.27"


def test_core_version_without_a_manager():
    """Без ядра — прочерк, а не падение."""
    assert core_version(None) == UNKNOWN


def test_core_version_when_the_core_is_silent():
    """Ядро не ответило: строка остаётся прочерком."""
    manager = type("Manager", (), {"get_version": lambda _self: None})()

    assert core_version(manager) == UNKNOWN


def test_core_version_survives_a_failing_manager():
    """Опрос версии не вправе ронять открытие диалога."""

    class Manager:
        def get_version(self):
            raise RuntimeError("ядро не найдено")

    assert core_version(Manager()) == UNKNOWN
