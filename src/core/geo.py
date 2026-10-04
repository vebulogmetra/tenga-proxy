"""Каталог geo-категорий из geosite.dat и geoip.dat.

Ссылка на категорию, которой нет в базе, — не пустое правило: ядро отвергает
конфиг целиком, и подключение не поднимается. Здесь читаются только названия
категорий, чтобы сборщик конфига мог отсеять неизвестные заранее.

Файлы — protobuf (`GeoSiteList` / `GeoIPList`): повторяющееся поле 1, внутри
которого поле 1 — название категории. Остальное содержимое записи пропускается
по длине, поэтому базы на десятки мегабайт читаются за десятки миллисекунд и
без protobuf-библиотеки.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.core.config import BUNDLE_DIR, CORE_DIR

logger = logging.getLogger("tenga.core.geo")

GEOSITE_FILE = "geosite.dat"
GEOIP_FILE = "geoip.dat"
ASSET_ENV = "XRAY_LOCATION_ASSET"
# Базы, скачанные пользователем по кнопке «Обновить» (src/core/geo_update.py).
USER_GEO_DIR = CORE_DIR / "geo"
# Базы из комплекта приложения: в AppImage и в дереве исходников они лежат здесь.
BUNDLED_GEO_DIR = BUNDLE_DIR / "core" / "bin"
# Куда ядро заглядывает, если рядом с бинарником файла нет.
SYSTEM_ASSET_DIRS = (Path("/usr/local/share/xray"), Path("/usr/share/xray"))

GEOSITE_PREFIX = "geosite:"
GEOIP_PREFIX = "geoip:"

# Готовые правила «Российские сайты» ссылаются на эти категории. Они проходят по
# каталогу, как и пользовательские: без них в базе правило просто не пишется.
RU_DIRECT_GEOSITES = ("geosite:category-ru", "geosite:category-gov-ru")
RU_DIRECT_GEOIP = "geoip:ru"
# Без этих категорий базу устанавливать нельзя.
REQUIRED_RULES = (*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP, "geoip:private")

# Поле 1, тип «строка байтов» — и у записи списка, и у названия внутри записи.
_LENGTH_DELIMITED_FIELD_1 = 0x0A


def _read_varint(data: memoryview, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def parse_categories(raw: bytes | memoryview) -> frozenset[str]:
    """Названия категорий базы в нижнем регистре.

    Raises:
        ValueError, IndexError, UnicodeDecodeError: содержимое — не геобаза.
    """
    data = memoryview(raw)
    names: set[str] = set()
    pos, size = 0, len(data)
    while pos < size:
        tag, pos = _read_varint(data, pos)
        if tag != _LENGTH_DELIMITED_FIELD_1:
            raise ValueError(f"неожиданное поле {tag:#x}")
        length, pos = _read_varint(data, pos)
        end = pos + length
        if end > size:
            raise ValueError("запись выходит за конец файла")

        entry = data[pos:end]
        inner_tag, inner = _read_varint(entry, 0)
        if inner_tag == _LENGTH_DELIMITED_FIELD_1:
            name_length, inner = _read_varint(entry, inner)
            if inner + name_length > len(entry):
                raise ValueError("название категории выходит за конец записи")
            names.add(bytes(entry[inner : inner + name_length]).decode("utf-8").lower())
        pos = end
    return frozenset(names)


def read_categories(path: Path) -> frozenset[str]:
    """Названия категорий базы в нижнем регистре; пусто, если файла нет или он битый."""
    try:
        data = path.read_bytes()
    except OSError:
        return frozenset()
    try:
        return parse_categories(data)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        logger.warning("Геобаза %s повреждена: %s", path, e)
        return frozenset()


@dataclass(frozen=True)
class GeoCatalog:
    """Какие категории можно упоминать в правилах, не уронив ядро."""

    geosite: frozenset[str] = frozenset()
    geoip: frozenset[str] = frozenset()

    def knows(self, rule: str) -> bool:
        """Есть ли категория правила `geosite:имя[@атрибут]` / `geoip:имя` в базе."""
        if rule.startswith(GEOSITE_PREFIX):
            # Атрибут не проверяем: неизвестный атрибут ядро принимает (пустой набор).
            return rule[len(GEOSITE_PREFIX) :].partition("@")[0] in self.geosite
        if rule.startswith(GEOIP_PREFIX):
            return rule[len(GEOIP_PREFIX) :] in self.geoip
        return True

    def split(self, rules: Iterable[str]) -> tuple[list[str], list[str]]:
        """Разделить правила на пригодные и ссылающиеся на неизвестную категорию."""
        kept: list[str] = []
        dropped: list[str] = []
        for rule in rules:
            (kept if self.knows(rule) else dropped).append(rule)
        return kept, dropped


def _has_bases(directory: Path) -> bool:
    return (directory / GEOSITE_FILE).is_file() and (directory / GEOIP_FILE).is_file()


def missing_required(catalog: GeoCatalog) -> list[str]:
    """Категории готовых правил, которых нет в базах."""
    return [rule for rule in REQUIRED_RULES if not catalog.knows(rule)]


def _downloaded_bases_usable() -> bool:
    """Годны ли базы из каталога обновлений.

    Битый или неполный файл там не должен ломать запуск: тогда каталог
    пропускается и работают базы из комплекта.
    """
    if not _has_bases(USER_GEO_DIR):
        return False
    return not missing_required(load_catalog([USER_GEO_DIR]))


def asset_dir_for_core(binary_path: str | Path | None) -> Path | None:
    """Каталог геобаз, который надо назвать ядру через `XRAY_LOCATION_ASSET`.

    None — называть нечего: каталог уже задан пользователем, базы лежат рядом с
    бинарником (там ядро найдёт их само) или их нет нигде. Обновлённые
    пользователем базы главнее тех, что рядом с бинарником.
    """
    if os.environ.get(ASSET_ENV):
        return None
    if _downloaded_bases_usable():
        return USER_GEO_DIR
    if binary_path and _has_bases(Path(binary_path).parent):
        return None
    if _has_bases(BUNDLED_GEO_DIR):
        return BUNDLED_GEO_DIR
    return None


def asset_dirs(binary_path: str | Path | None) -> list[Path]:
    """Каталоги, где окажутся геобазы ядра, в порядке поиска.

    Повторяет поиск самого ядра (`XRAY_LOCATION_ASSET`, иначе каталог бинарника,
    затем системные) с поправкой на то, что называет ядру `asset_dir_for_core`:
    годные базы из каталога обновлений, а если рядом с бинарником баз нет —
    каталог комплекта приложения.
    """
    dirs: list[Path] = []
    env_dir = os.environ.get(ASSET_ENV)
    if env_dir:
        dirs.append(Path(env_dir))
    else:
        if _downloaded_bases_usable():
            dirs.append(USER_GEO_DIR)
        if binary_path:
            dirs.append(Path(binary_path).parent)
        dirs.append(BUNDLED_GEO_DIR)
    dirs.extend(SYSTEM_ASSET_DIRS)
    return dirs


def find_geo_file(name: str, dirs: Iterable[Path]) -> Path | None:
    for directory in dirs:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


# Ключ — путь, размер и время изменения: заменённый файл перечитывается сам.
_cache: dict[tuple[str, int, int], frozenset[str]] = {}


def _cached_categories(path: Path | None) -> frozenset[str]:
    if path is None:
        return frozenset()
    try:
        stat = path.stat()
    except OSError:
        return frozenset()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _cache:
        _cache[key] = read_categories(path)
    return _cache[key]


def load_catalog(dirs: Iterable[Path]) -> GeoCatalog:
    """Каталог по первым найденным geosite.dat и geoip.dat."""
    dirs = list(dirs)
    return GeoCatalog(
        geosite=_cached_categories(find_geo_file(GEOSITE_FILE, dirs)),
        geoip=_cached_categories(find_geo_file(GEOIP_FILE, dirs)),
    )
