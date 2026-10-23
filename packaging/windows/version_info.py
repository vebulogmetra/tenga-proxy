"""Ресурс версии для tenga-proxy.exe (свойства файла в Проводнике).

    python packaging/windows/version_info.py build/windows/version_info.txt

Пишет файл в формате `VSVersionInfo` PyInstaller; версия берётся из
`src/__init__.py`, поэтому `cli.py bump-version` о Windows знать не нужно.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Artem G.'),
        StringStruct('FileDescription', 'Tenga Proxy'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'tenga-proxy'),
        StringStruct('OriginalFilename', 'tenga-proxy.exe'),
        StringStruct('ProductName', 'Tenga Proxy'),
        StringStruct('ProductVersion', '{version}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def project_version() -> str:
    text = (ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "(.+?)"', text)
    if match is None:
        raise RuntimeError("__version__ not found in src/__init__.py")
    return match.group(1)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """Четыре числа ресурса версии; суффиксы вроде `rc1` отбрасываются."""
    numbers = [int(re.match(r"\d*", part).group() or 0) for part in version.split(".")[:4]]
    return tuple(numbers + [0] * (4 - len(numbers)))


def render(version: str) -> str:
    return TEMPLATE.format(numbers=version_tuple(version), version=version)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(project_version()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
