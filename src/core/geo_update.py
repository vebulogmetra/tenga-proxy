"""Обновление геобаз по запросу пользователя.

Базы скачиваются в каталог конфигурации (`geo/`), рядом со встроенными не
ложатся и их не заменяют: испорченное обновление всегда можно обойти, вернувшись
к базам из комплекта (см. `src/core/geo.py`).

Файл устанавливается, только если совпала контрольная сумма из того же релиза и
в базе есть категории, на которые ссылаются готовые правила. Обе базы меняются
вместе: сначала всё проверяется, потом переименовывается.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import requests

from src.core.geo import (
    GEOIP_FILE,
    GEOSITE_FILE,
    GeoCatalog,
    missing_required,
    parse_categories,
)

logger = logging.getLogger("tenga.core.geo_update")

# Тот же источник, из которого берёт базы сборка самого xray-core.
GEO_SOURCE = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download"
MAX_BASE_SIZE = 64 * 1024 * 1024
MAX_CHECKSUM_SIZE = 4096

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

Fetch = Callable[[str, int], bytes]


class GeoUpdateError(Exception):
    """Обновление не установлено; прежние базы остались на месте."""


def _http_fetch(url: str, limit: int) -> bytes:
    """Скачать файл, не принимая больше `limit` байт."""
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=1 << 16):
                size += len(chunk)
                if size > limit:
                    raise GeoUpdateError(f"{url}: файл больше {limit} байт")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as e:
        raise GeoUpdateError(f"{url}: {e}") from e


def _expected_sha256(checksum_file: bytes, name: str) -> str:
    """Сумма из файла `.sha256sum` (формат `sha256sum`: «сумма  имя»)."""
    parts = checksum_file.decode("ascii", errors="replace").split()
    digest = parts[0].lower() if parts else ""
    if not _SHA256.match(digest):
        raise GeoUpdateError(f"{name}: файл контрольной суммы не разобран")
    return digest


def _download_verified(name: str, fetch: Fetch) -> bytes:
    data = fetch(f"{GEO_SOURCE}/{name}", MAX_BASE_SIZE)
    expected = _expected_sha256(fetch(f"{GEO_SOURCE}/{name}.sha256sum", MAX_CHECKSUM_SIZE), name)
    if hashlib.sha256(data).hexdigest() != expected:
        raise GeoUpdateError(f"{name}: контрольная сумма не совпала")
    return data


def _categories(name: str, data: bytes) -> frozenset[str]:
    try:
        return parse_categories(data)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        raise GeoUpdateError(f"{name}: файл повреждён ({e})") from e


def update_geo_bases(target_dir: Path, *, fetch: Fetch = _http_fetch) -> GeoCatalog:
    """Скачать, проверить и установить обе базы.

    Raises:
        GeoUpdateError: что-то не сошлось; в `target_dir` ничего не изменилось.
    """
    bases = {name: _download_verified(name, fetch) for name in (GEOSITE_FILE, GEOIP_FILE)}
    catalog = GeoCatalog(
        geosite=_categories(GEOSITE_FILE, bases[GEOSITE_FILE]),
        geoip=_categories(GEOIP_FILE, bases[GEOIP_FILE]),
    )
    missing = missing_required(catalog)
    if missing:
        raise GeoUpdateError("в скачанных базах нет категорий: " + ", ".join(missing))

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Все временные файлы — на той же файловой системе: rename атомарен.
        # Сохраняем предыдущую пару до первой замены, чтобы ошибка второй
        # не оставила одну новую базу рядом с одной старой.
        with tempfile.TemporaryDirectory(prefix=".geo-update-", dir=target_dir) as work:
            staging = Path(work)
            backups: dict[str, Path | None] = {}
            for name, data in bases.items():
                (staging / name).write_bytes(data)
                destination = target_dir / name
                backup = staging / f"{name}.backup" if destination.exists() else None
                if backup is not None:
                    shutil.copy2(destination, backup)
                backups[name] = backup

            installed: list[str] = []
            try:
                for name in bases:
                    os.replace(staging / name, target_dir / name)
                    installed.append(name)
            except OSError:
                for name in reversed(installed):
                    backup = backups[name]
                    if backup is None:
                        (target_dir / name).unlink(missing_ok=True)
                    else:
                        os.replace(backup, target_dir / name)
                raise
    except OSError as e:
        raise GeoUpdateError(f"не удалось записать базы: {e}") from e

    logger.info("Геобазы обновлены: %s", target_dir)
    return catalog
