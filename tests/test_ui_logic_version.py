from __future__ import annotations

import src
from src.core.core_update import AVAILABLE, BEHIND_PINNED, CURRENT, CoreUpdateStatus
from src.core.core_update import UNKNOWN as UPDATE_UNKNOWN
from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version


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


# --- обновление ядра ---


def test_core_update_text_names_the_available_version():
    status = CoreUpdateStatus(AVAILABLE, installed="26.9.9", target="26.9.30")

    assert core_update_text(status) == "Доступна версия 26.9.30"


def test_core_update_text_warns_about_a_core_older_than_expected():
    status = CoreUpdateStatus(BEHIND_PINNED, installed="26.3.27", target="26.9.9")

    assert core_update_text(status) == "Ядро старее версии 26.9.9, на которую рассчитано приложение"


def test_core_update_text_for_a_current_core():
    assert core_update_text(CoreUpdateStatus(CURRENT, installed="26.9.30")) == "Обновлений нет"


def test_core_update_text_before_the_first_check():
    assert (
        core_update_text(CoreUpdateStatus(UPDATE_UNKNOWN, installed="26.9.9")) == "Не проверялось"
    )
