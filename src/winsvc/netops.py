"""Изменения сети Windows: маршруты и DNS через netsh, NRPT через PowerShell.

Интерфейсы задаются индексом: в именах бывают пробелы и скобки, а индекс —
просто число. Каждый аргумент проверяется до сборки команды: служба работает от
SYSTEM. Маршруты ставятся с `store=active` и исчезают при перезагрузке; правила
NRPT хранятся в реестре, поэтому у них есть комментарий для уборки.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
from collections.abc import Callable

from src.core.platform_info import no_window

logger = logging.getLogger("tenga.winsvc.netops")

NRPT_COMMENT = "tenga-proxy"
_GUID = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)
_NETSH_ROUTE = ["netsh", "interface", "ipv4"]


def _index(value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"bad interface index: {value!r}")
    return value


def _ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError as e:
        raise ValueError(f"bad IPv4 address: {value!r}") from e


def _prefix(value: str) -> str:
    try:
        return str(ipaddress.IPv4Network(value))
    except ValueError as e:
        raise ValueError(f"bad IPv4 prefix: {value!r}") from e


def route_add(prefix: str, index: int, nexthop: str | None = None) -> list[str]:
    cmd = [*_NETSH_ROUTE, "add", "route", f"prefix={_prefix(prefix)}", f"interface={_index(index)}"]
    if nexthop:
        cmd.append(f"nexthop={_ipv4(nexthop)}")
    return [*cmd, "metric=1", "store=active"]


def route_delete(prefix: str, index: int) -> list[str]:
    return [
        *_NETSH_ROUTE,
        "delete",
        "route",
        f"prefix={_prefix(prefix)}",
        f"interface={_index(index)}",
        "store=active",
    ]


def set_dns(index: int, server: str) -> list[str]:
    return [
        *_NETSH_ROUTE,
        "set",
        "dnsservers",
        f"name={_index(index)}",
        "source=static",
        f"address={_ipv4(server)}",
        "register=none",
        "validate=no",
    ]


def set_metric(index: int, metric: int = 1) -> list[str]:
    return [
        *_NETSH_ROUTE,
        "set",
        "interface",
        f"interface={_index(index)}",
        f"metric={int(metric)}",
    ]


def nrpt_add_script(server: str) -> str:
    return (
        f"(Add-DnsClientNrptRule -Namespace '.' -NameServers '{_ipv4(server)}' "
        f"-Comment '{NRPT_COMMENT}' -PassThru).Name; Clear-DnsClientCache"
    )


def nrpt_remove_script(name: str) -> str:
    if not _GUID.fullmatch(name):
        raise ValueError(f"bad NRPT rule name: {name!r}")
    return f"Remove-DnsClientNrptRule -Name '{name}' -Force; Clear-DnsClientCache"


NRPT_SWEEP_SCRIPT = (
    f"Get-DnsClientNrptRule | Where-Object Comment -eq '{NRPT_COMMENT}' | "
    "ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force }; Clear-DnsClientCache"
)


def _run(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False, **no_window()
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("%s failed: %s", cmd[:5], e)
        return False
    if result.returncode != 0:
        logger.warning("%s returned %s: %s", cmd, result.returncode, result.stdout.strip())
    return result.returncode == 0


class NetOps:
    """Исполнитель команд; в тестах подменяется `run` и `powershell`."""

    def __init__(self, run: Callable[[list[str]], bool] = _run, powershell=None) -> None:
        if powershell is None:
            from src.sys.windows.powershell import run_json as powershell
        self._run = run
        self._powershell = powershell

    def run(self, cmd: list[str]) -> bool:
        return self._run(cmd)

    def nrpt_add(self, server: str) -> str | None:
        name = self._powershell(nrpt_add_script(server)).strip().splitlines()
        return name[0] if name and _GUID.fullmatch(name[0]) else None

    def nrpt_sweep(self) -> None:
        self._powershell(NRPT_SWEEP_SCRIPT)

    def undo(self, entry: dict) -> None:
        if entry["op"] == "route.delete":
            self._run(route_delete(entry["prefix"], entry["index"]))
        elif entry["op"] == "nrpt.remove":
            self._powershell(nrpt_remove_script(entry["name"]))
