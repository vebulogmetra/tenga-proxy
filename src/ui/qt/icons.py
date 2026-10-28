"""Картинки Qt-интерфейса: флаги стран и логотип по состоянию.

Флаги — svg из комплекта: эмодзи-флагов в шрифтах Windows нет, а Qt рисует
svg одинаково на обеих системах.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtGui import QIcon

from src.core.config import get_asset_path
from src.ui.logic.country_flags import split_flag_prefix


@cache
def flag_icon(code: str) -> QIcon | None:
    path = get_asset_path(f"flags/{code}.svg")
    if not path.is_file():
        return None
    return QIcon(str(path))


def flagged(text: str) -> tuple[QIcon | None, str]:
    """Флаг в начале имени — иконкой, остальное — текстом.

    Без картинки для кода имя остаётся как есть, с эмодзи.
    """
    code, rest = split_flag_prefix(text)
    icon = flag_icon(code) if code else None
    if icon is None:
        return None, text
    return icon, rest
