"""Отпечаток сети на Linux: маршрут по умолчанию мимо TUN."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable

from src.sys.linux.netbind import _tun_devices


def parse_default_route(text: str, exclude: Iterable[str] = ()) -> tuple[str, str] | None:
    """(шлюз, интерфейс) маршрута по умолчанию с наименьшей метрикой из `ip route`.

    Шлюза у маршрута может не быть (PPP, точка-точка): тогда он пустой.
    """
    skipped = set(exclude)
    best: tuple[int, str, str] | None = None
    for line in text.splitlines():
        parts = line.split()
        if parts[:1] != ["default"]:
            continue
        fields = dict(zip(parts[1::2], parts[2::2], strict=False))
        dev = fields.get("dev", "")
        if not dev or dev in skipped:
            continue
        try:
            metric = int(fields.get("metric", "0"))
        except ValueError:
            metric = 0
        if best is None or metric < best[0]:
            best = (metric, fields.get("via", ""), dev)
    return None if best is None else (best[1], best[2])


def default_route() -> tuple[str, str] | None:
    """(шлюз, интерфейс) физического маршрута по умолчанию или None, если его нет."""
    try:
        result = subprocess.run(
            ["ip", "-4", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_default_route(result.stdout, exclude=_tun_devices())
