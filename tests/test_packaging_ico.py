"""ICO из PNG-кадров: заголовок и каталог по спецификации."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "ico.py"
_SPEC = importlib.util.spec_from_file_location("ico", _PATH)
_ico = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ico)
build_ico = _ico.build_ico

PNG_16 = b"\x89PNG\r\n\x1a\n" + b"a" * 20
PNG_256 = b"\x89PNG\r\n\x1a\n" + b"b" * 30


def test_header_counts_images():
    data = build_ico([(16, PNG_16), (256, PNG_256)])

    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, 2)


def test_directory_points_at_png_payloads():
    data = build_ico([(16, PNG_16), (256, PNG_256)])

    width, height, _colors, _res, _planes, bpp, size, offset = struct.unpack_from(
        "<BBBBHHII", data, 6
    )
    assert (width, height, bpp) == (16, 16, 32)
    assert data[offset : offset + size] == PNG_16

    width, height, *_rest, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16)
    # 256 пикселей записываются нулём: поле занимает один байт.
    assert (width, height) == (0, 0)
    assert data[offset : offset + size] == PNG_256
