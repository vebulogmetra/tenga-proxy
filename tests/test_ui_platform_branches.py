"""Где интерфейс вправе проверять ОС напрямую.

Отличия текстов собраны в `platform_texts`, компоновки — в `platform_layout`.
Напрямую `IS_WINDOWS` читают только места, где меняется поведение, а не вид:
флаги GApplication, сигналы и активация второго запуска, выбор трея.
Новое отличие добавляется в один из двух модулей, а не `if` в виджете.
"""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "ui"

ALLOWED = {
    "logic/platform_texts.py",
    "logic/platform_layout.py",
    "application.py",
    "tray/controller.py",
}


def test_only_known_places_check_the_platform():
    offenders = sorted(
        path.relative_to(UI).as_posix()
        for path in UI.rglob("*.py")
        if "IS_WINDOWS" in path.read_text(encoding="utf-8")
    )

    assert set(offenders) <= ALLOWED, f"IS_WINDOWS вне platform_texts/platform_layout: {offenders}"
