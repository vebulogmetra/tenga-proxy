"""Где интерфейс вправе проверять ОС напрямую.

Отличия текстов собраны в `platform_texts`. GTK-интерфейс работает только на
Linux, Qt-интерфейс ОС не проверяет: Windows выбирает его в `gui.py`.
Напрямую `IS_WINDOWS` читает только выбор трея.
"""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "ui"

ALLOWED = {
    "logic/platform_texts.py",
    "tray/controller.py",
}


def test_only_known_places_check_the_platform():
    offenders = sorted(
        path.relative_to(UI).as_posix()
        for path in UI.rglob("*.py")
        if "IS_WINDOWS" in path.read_text(encoding="utf-8")
    )

    assert set(offenders) <= ALLOWED, f"IS_WINDOWS вне platform_texts: {offenders}"
