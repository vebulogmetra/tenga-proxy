"""Сборка ICO из готовых PNG-кадров.

С Windows Vista ICO может хранить кадры в PNG как есть, поэтому кодировать
пиксели не нужно: заголовок, каталог по 16 байт на кадр и сами PNG подряд.
"""

from __future__ import annotations

import struct

_HEADER = struct.Struct("<HHH")
_ENTRY = struct.Struct("<BBBBHHII")


def build_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """`frames` — пары (размер стороны, PNG-байты), размер от 1 до 256."""
    offset = _HEADER.size + _ENTRY.size * len(frames)
    directory = b""
    for size, png in frames:
        side = 0 if size >= 256 else size
        directory += _ENTRY.pack(side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return _HEADER.pack(0, 1, len(frames)) + directory + b"".join(png for _, png in frames)
