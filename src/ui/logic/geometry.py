"""Parsing and formatting of the persisted window geometry.

Настройки хранят геометрию одной строкой вида `w,h,x,y,maximized`.
Координаты достались от GTK3. Позиционировать окна GTK4 не умеет, поэтому они
читаются и отбрасываются, записываются нулями: файл настроек должен
оставаться пригодным для старого интерфейса, пока тот не удалён.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_WIDTH = 360
MIN_HEIGHT = 400


@dataclass(frozen=True)
class Geometry:
    """Window size and maximized state."""

    width: int
    height: int
    maximized: bool = False


DEFAULT_GEOMETRY = Geometry(width=520, height=720, maximized=False)


def _int_at(parts: list[str], index: int, minimum: int, fallback: int) -> int:
    """Read one integer field, falling back per field rather than wholesale."""
    if index >= len(parts):
        return fallback
    try:
        value = int(parts[index])
    except ValueError:
        return fallback
    return max(value, minimum)


def parse_geometry(raw: str, *, default: Geometry = DEFAULT_GEOMETRY) -> Geometry:
    """Read a stored geometry string, tolerating anything malformed."""
    if not raw:
        return default

    parts = [part.strip() for part in raw.split(",")]
    return Geometry(
        width=_int_at(parts, 0, MIN_WIDTH, default.width),
        height=_int_at(parts, 1, MIN_HEIGHT, default.height),
        maximized=_int_at(parts, 4, 0, 0) == 1,
    )


def format_geometry(geometry: Geometry) -> str:
    """Serialize geometry back into the stored string form."""
    return f"{geometry.width},{geometry.height},0,0,{1 if geometry.maximized else 0}"
