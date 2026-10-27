"""Снимок сети Windows: адаптеры, их IPv4-адреса, DNS и маршруты по умолчанию.

Один вызов PowerShell возвращает всё сразу и кэшируется на пару секунд: при
подключении сборщик конфига подряд спрашивает интерфейс, DNS и состояние VPN.
Имя интерфейса — `InterfaceAlias` («Ethernet», «Wi-Fi»): его же понимают
`netsh` и `sockopt.interface` ядра.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

from src.sys.windows.powershell import run_json

CACHE_SECONDS = 2.0
# Первый вызов грузит модули NetTCPIP и CIM: на холодной системе это дольше
# стандартных 15 секунд PowerShell-обёртки.
SNAPSHOT_TIMEOUT = 45

SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$result = @{
  adapters = @(Get-NetAdapter -IncludeHidden | ForEach-Object {
    @{ alias = $_.Name; index = $_.ifIndex; status = [string]$_.Status;
       description = $_.InterfaceDescription } })
  ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
    @{ alias = $_.InterfaceAlias; ip = $_.IPAddress; index = $_.InterfaceIndex } })
  dns = @(Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    ForEach-Object { @{ alias = $_.InterfaceAlias; servers = @($_.ServerAddresses) } })
  routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' `
      -ErrorAction SilentlyContinue | ForEach-Object {
    $if = Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4 `
      -ErrorAction SilentlyContinue
    @{ alias = $_.InterfaceAlias; index = $_.ifIndex; nexthop = $_.NextHop;
       metric = $_.RouteMetric; ifmetric = [int]$if.InterfaceMetric } })
}
$result | ConvertTo-Json -Depth 5 -Compress
"""

# Описания адаптеров туннелей и VPN: через них нельзя выходить «напрямую».
_TUNNEL_MARKERS = ("wintun", "wireguard", "tap-windows", "openvpn", "wan miniport", "ppp")


@dataclass
class Adapter:
    alias: str
    index: int
    status: str
    description: str
    ipv4: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    # Нет в Get-NetAdapter: так выглядят PPP-интерфейсы встроенных VPN.
    listed: bool = True


@dataclass(frozen=True)
class Route:
    alias: str
    index: int
    nexthop: str
    metric: int


@dataclass
class NetSnapshot:
    adapters: list[Adapter] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)

    def adapter(self, alias: str) -> Adapter | None:
        return next((a for a in self.adapters if a.alias == alias), None)


def _as_list(value) -> list[dict]:
    """Список объектов; PowerShell сворачивает массив из одного элемента в объект."""
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, dict)]


def parse_snapshot(text: str) -> NetSnapshot:
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        return NetSnapshot()
    if not isinstance(data, dict):
        return NetSnapshot()

    adapters = {}
    for item in _as_list(data.get("adapters")):
        alias = str(item.get("alias", ""))
        if alias:
            adapters[alias] = Adapter(
                alias=alias,
                index=int(item.get("index") or 0),
                status=str(item.get("status", "")),
                description=str(item.get("description", "")),
            )
    for item in _as_list(data.get("ips")):
        alias, ip = str(item.get("alias", "")), str(item.get("ip") or "")
        if not alias or not ip:
            continue
        adapter = adapters.get(alias)
        if adapter is None:
            if ip.startswith("127."):
                # Loopback Pseudo-Interface: в адаптерах его нет, но и VPN он не является.
                continue
            adapter = adapters[alias] = Adapter(
                alias=alias,
                index=int(item.get("index") or 0),
                status="Up",
                description="",
                listed=False,
            )
        adapter.ipv4.append(ip)
    for item in _as_list(data.get("dns")):
        adapter = adapters.get(str(item.get("alias", "")))
        if adapter:
            servers = item.get("servers") or []
            adapter.dns.extend(
                str(s) for s in (servers if isinstance(servers, list) else [servers])
            )

    routes = [
        Route(
            alias=str(item.get("alias", "")),
            index=int(item.get("index") or 0),
            nexthop=str(item.get("nexthop", "")),
            metric=int(item.get("metric") or 0) + int(item.get("ifmetric") or 0),
        )
        for item in _as_list(data.get("routes"))
    ]
    return NetSnapshot(adapters=list(adapters.values()), routes=routes)


def is_tunnel(adapter: Adapter | None) -> bool:
    if adapter is None:
        return False
    if not adapter.listed:
        # Не сетевой адаптер — значит, и не физический интерфейс.
        return True
    description = adapter.description.lower()
    return any(marker in description for marker in _TUNNEL_MARKERS)


def default_route(snapshot: NetSnapshot, exclude=()) -> Route | None:
    """Маршрут по умолчанию через физический интерфейс с наименьшей метрикой."""
    skipped = set(exclude)
    candidates = [
        route
        for route in snapshot.routes
        if route.alias not in skipped and not is_tunnel(snapshot.adapter(route.alias))
    ]
    return min(candidates, key=lambda route: route.metric, default=None)


_lock = threading.Lock()
_cached: tuple[float, NetSnapshot] | None = None


def invalidate() -> None:
    global _cached
    with _lock:
        _cached = None


def snapshot() -> NetSnapshot:
    global _cached
    with _lock:
        now = time.monotonic()
        if _cached is not None and now - _cached[0] < CACHE_SECONDS:
            return _cached[1]
        result = parse_snapshot(run_json(SCRIPT, timeout=SNAPSHOT_TIMEOUT))
        # A cold PowerShell query can take longer than CACHE_SECONDS itself.
        # Start the reuse window after it finishes, otherwise the next caller
        # immediately launches the same expensive query again.
        _cached = (time.monotonic(), result)
        return result
