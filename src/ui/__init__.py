"""UI package.

Реэкспорт GTK3-приложения сделан ленивым: импорт `src.ui.app` фиксирует
`Gtk 3.0` в процессе, после чего GTK4-модули этого же пакета загрузить уже
нельзя. Версию выбирает точка входа, пока сосуществуют два интерфейса.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.ui.app import TengaApp, run_app

__all__ = [
    "TengaApp",
    "run_app",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from src.ui import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
