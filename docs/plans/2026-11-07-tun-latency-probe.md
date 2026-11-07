# Замер задержки при активном TUN: план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Замер задержки работает при активном TUN и в состоянии «трафик заблокирован», меряя
каждый сервер напрямую, мимо туннеля, на Linux и Windows.

**Architecture:** Пробное ядро получает `ProbeRoute` (физический интерфейс, метка, DNS сети) и
привязывает свои outbound'ы к интерфейсу теми же функциями, что рабочий конфиг. На Linux
помощник ставит на TUN разбитый маршрут `0.0.0.0/1` + `128.0.0.0/1` вместо замены маршрута по
умолчанию, поэтому физический маршрут остаётся всегда. Дизайн:
`docs/plans/2026-11-07-tun-latency-probe-design.md`.

**Tech Stack:** Python 3.11, xray-core (`sockopt.interface`, `sockopt.mark`, `dns`), POSIX sh
(`core/scripts/tun_route_helper.sh`), nftables, pytest; QEMU-лаборатория `make test-vm`.

**Правила репозитория:** коммиты одной строкой, без co-author trailer'ов. Линтер `make lint`
(ruff, 100 символов). На машине разработчика TUN не запускать: `xray0` занят живым сеансом;
помощника и `nft` тоже не трогать.

Команда тестов: `uv run pytest <файл> -q`. После каждой задачи — `make lint`.

---

### Task 1: Общие функции опций сокетов

Вынести привязку, метку и разрешение имени из `src/core/config_builder.py` в новый модуль,
чтобы пробное ядро не копировало их.

**Files:**
- Create: `src/core/sockopt.py`
- Modify: `src/core/config_builder.py:107-134` (`_is_loopback`, `_is_ip`, `_bind_to_interface`,
  `_prepare_tun_sockets`)
- Test: `tests/test_core_sockopt.py`

**Step 1: Тест**

```python
"""Опции сокетов outbound'ов, общие для рабочего и пробного ядра."""

from __future__ import annotations

import pytest

from src.core.sockopt import (
    bind_to_interface,
    is_ip,
    is_loopback,
    mark_socket,
    resolve_in_core,
)


def test_bind_creates_stream_settings_and_keeps_other_options():
    outbound = {"protocol": "freedom", "streamSettings": {"sockopt": {"tcpFastOpen": True}}}

    bind_to_interface(outbound, "eth0")
    mark_socket(outbound, 0x7E6A)
    resolve_in_core(outbound)

    assert outbound["streamSettings"]["sockopt"] == {
        "tcpFastOpen": True,
        "interface": "eth0",
        "mark": 0x7E6A,
        "domainStrategy": "UseIPv4",
    }


def test_bind_without_stream_settings():
    outbound = {"protocol": "freedom"}
    bind_to_interface(outbound, "eth0")
    assert outbound["streamSettings"] == {"sockopt": {"interface": "eth0"}}


@pytest.mark.parametrize(
    ("host", "loopback", "ip"),
    [
        ("localhost", True, False),
        ("127.0.0.1", True, True),
        ("::1", True, True),
        ("203.0.113.5", False, True),
        ("[2001:db8::1]", False, True),
        ("srv.example.com", False, False),
    ],
)
def test_loopback_and_ip_detection(host, loopback, ip):
    assert is_loopback(host) is loopback
    assert is_ip(host) is ip
```

**Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/test_core_sockopt.py -q`
Expected: `ModuleNotFoundError: No module named 'src.core.sockopt'`

**Step 3: Модуль**

```python
"""Опции сокетов outbound'ов: привязка к интерфейсу, метка, разрешение имени в ядре.

Общие для рабочего конфига (`config_builder`) и пробного ядра (`batch_probe`): оба
должны выходить в сеть мимо туннеля одинаково.
"""

from __future__ import annotations

import ipaddress


def _sockopt(outbound: dict) -> dict:
    return outbound.setdefault("streamSettings", {}).setdefault("sockopt", {})


def bind_to_interface(outbound: dict, interface: str) -> None:
    """SO_BINDTODEVICE на Linux, IP_UNICAST_IF на Windows: маршрут ищется только на интерфейсе."""
    _sockopt(outbound)["interface"] = interface


def mark_socket(outbound: dict, mark: int) -> None:
    """Метка пропускает трафик ядра мимо таблицы `inet veblock` (см. tun_route_helper.sh)."""
    _sockopt(outbound)["mark"] = mark


def resolve_in_core(outbound: dict) -> None:
    """Имя сервера разрешает DNS-модуль ядра, а не системный резолвер.

    Системный резолвер шлёт запрос без метки и привязки, то есть в туннель. На SNI это
    не влияет: `serverName` не меняется.
    """
    _sockopt(outbound)["domainStrategy"] = "UseIPv4"


def is_loopback(host: str) -> bool:
    """Сервер на этой же машине (локальный обфускатор): через сетевой интерфейс не достать."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True
```

**Step 4: Тест проходит**

Run: `uv run pytest tests/test_core_sockopt.py -q`
Expected: PASS

**Step 5: `config_builder` переходит на модуль**

В `src/core/config_builder.py`: удалить `_is_loopback`, `_is_ip`, `_bind_to_interface`
(строки 107–124), добавить импорт

```python
from src.core.sockopt import bind_to_interface, is_ip, is_loopback, mark_socket, resolve_in_core
```

и заменить вызовы: `_bind_to_interface(` → `bind_to_interface(`, `_is_loopback(` →
`is_loopback(`. `_prepare_tun_sockets` становится:

```python
def _prepare_tun_sockets(outbounds: list[dict], proxy_outbound: dict, server: str) -> None:
    """Сокеты ядра в TUN: метка на всех outbound'ах и разрешение имени сервера внутри ядра."""
    for outbound in outbounds:
        if outbound.get("protocol") != "blackhole":
            mark_socket(outbound, SOCKET_MARK)
    if not is_ip(server) and not is_loopback(server):
        resolve_in_core(proxy_outbound)
```

Импорт `ipaddress` в `config_builder.py` после этого не нужен, если ruff так скажет.

**Step 6: Все тесты билдера проходят**

Run: `uv run pytest tests/test_core_config_builder.py tests/test_core_sockopt.py -q && make lint`
Expected: PASS, lint чистый

**Step 7: Commit**

```bash
git add src/core/sockopt.py src/core/config_builder.py tests/test_core_sockopt.py
git commit -m "core: вынести опции сокетов outbound'ов в модуль"
```

---

### Task 2: `ProbeRoute` в пробном ядре

**Files:**
- Modify: `src/core/batch_probe.py`
- Test: `tests/test_core_batch_probe.py`

**Step 1: Тесты**

В `tests/test_core_batch_probe.py` добавить в импорт из `src.core.batch_probe` имя `ProbeRoute`,
рядом с константами ссылок:

```python
VLESS_REMOTE = f"vless://{UUID}@203.0.113.5:443?type=tcp&security=tls&sni=a.example.com#R"
VLESS_NAMED = f"vless://{UUID}@srv.example.com:443?type=tcp&security=tls&sni=a.example.com#N"
ROUTE = ProbeRoute(interface="eth0", mark=0x7E6A, dns_servers=("192.168.0.1",))
```

Помощник `target()` должен передавать адрес сервера:

```python
def target(profile_id: int, link: str) -> ProbeTarget:
    profile = entry(profile_id, link)
    outbound = build_probe_outbound(profile, DataStore())
    assert outbound is not None, link
    return ProbeTarget(profile_id, outbound, server=profile.bean.server_address)
```

Новый раздел тестов (после тестов конфига пакета):

```python
# --- путь мимо туннеля ---


def sockopt(outbound: dict) -> dict:
    return outbound.get("streamSettings", {}).get("sockopt", {})


def test_route_binds_and_marks_every_remote_proxy():
    targets = [target(1, VLESS_REMOTE), target(2, VLESS_NAMED), target(3, TROJAN)]

    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS, route=ROUTE)

    remote, named, local = config["outbounds"][:3]
    assert sockopt(remote)["interface"] == "eth0"
    assert sockopt(remote)["mark"] == 0x7E6A
    assert "domainStrategy" not in sockopt(remote)
    assert sockopt(named)["domainStrategy"] == "UseIPv4"
    # Сервер на этой машине через сетевой интерфейс не достать, а метка ему не мешает.
    assert "interface" not in sockopt(local)
    assert sockopt(local)["mark"] == 0x7E6A


def test_route_adds_a_bound_direct_outbound_and_the_network_dns():
    config = build_batch_probe_config([target(1, VLESS_NAMED)], [41001], CREDENTIALS, route=ROUTE)

    direct = config["outbounds"][-1]
    assert (direct["protocol"], direct["tag"]) == ("freedom", "direct")
    assert sockopt(direct) == {"interface": "eth0", "mark": 0x7E6A}
    assert config["dns"] == {
        "servers": ["192.168.0.1"],
        "queryStrategy": "UseIPv4",
        "tag": "probe-dns",
    }
    # Без правила запросы DNS-модуля ушли бы в первый outbound, то есть в proxy-1.
    assert config["routing"]["rules"][0] == {
        "type": "field",
        "inboundTag": ["probe-dns"],
        "outboundTag": "direct",
    }


def test_route_without_mark_or_dns_leaves_them_out():
    config = build_batch_probe_config(
        [target(1, VLESS_REMOTE)], [41001], CREDENTIALS, route=ProbeRoute("Ethernet")
    )

    assert "mark" not in sockopt(config["outbounds"][0])
    assert "dns" not in config
    assert [rule["inboundTag"] for rule in config["routing"]["rules"]] == [["probe-in-1"]]


def test_without_route_the_config_is_untouched():
    config = build_batch_probe_config([target(1, VLESS_REMOTE)], [41001], CREDENTIALS)

    assert "dns" not in config
    assert [outbound["tag"] for outbound in config["outbounds"]] == ["proxy-1"]
    assert "interface" not in sockopt(config["outbounds"][0])


@needs_xray
def test_core_accepts_a_routed_batch():
    targets = [target(1, VLESS_NAMED), target(2, TROJAN), target(3, HYSTERIA2)]
    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS, route=ROUTE)

    assert core_accepts(str(XRAY), config) is True


def test_batch_builds_every_config_with_the_route(monkeypatch):
    routes = []
    real = batch_probe.build_batch_probe_config

    def building(targets, ports, credentials, **kwargs):
        routes.append(kwargs.get("route"))
        return real(targets, ports, credentials, **kwargs)

    monkeypatch.setattr(batch_probe, "build_batch_probe_config", building)
    monkeypatch.setattr(batch_probe, "core_accepts", lambda *_a, **_k: False)
    results: dict = {}

    probe_targets(
        [target(1, VLESS_REMOTE)], binary_path="/x", on_result=results.__setitem__, route=ROUTE
    )

    assert results == {1: -1}
    assert routes and all(route is ROUTE for route in routes)


def test_probe_profiles_passes_the_route_and_the_server_address(monkeypatch):
    seen: dict = {}

    def fake_probe_targets(targets, **options):
        seen.update(options)
        seen["servers"] = [t.server for t in targets]

    monkeypatch.setattr(batch_probe, "probe_targets", fake_probe_targets)

    probe_profiles(
        [entry(1, VLESS_NAMED)],
        settings=DataStore(),
        binary_path="/x",
        on_result=lambda *_: None,
        route=ROUTE,
    )

    assert seen["route"] is ROUTE
    assert seen["servers"] == ["srv.example.com"]
```

**Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: `ImportError: cannot import name 'ProbeRoute'`

**Step 3: Реализация**

В `src/core/batch_probe.py`:

```python
from src.core.sockopt import bind_to_interface, is_ip, is_loopback, mark_socket, resolve_in_core

DIRECT_TAG = "direct"
PROBE_DNS_TAG = "probe-dns"


@dataclass(frozen=True)
class ProbeRoute:
    """Путь пробы мимо туннеля: физический интерфейс, метка и DNS сети.

    Без него пробы ушли бы в TUN, то есть через текущий сервер. Метка нужна только на
    Linux: таблица `inet veblock` пропускает лишь помеченные сокеты.
    """

    interface: str
    mark: int | None = None
    dns_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeTarget:
    """Профиль, готовый к замеру: его id и собранный outbound."""

    profile_id: int
    outbound: dict[str, Any]
    # Адрес сервера из профиля: в outbound он лежит по-разному у каждого протокола.
    server: str = ""


def _route_past_tunnel(outbound: dict[str, Any], server: str, route: ProbeRoute) -> None:
    loopback = is_loopback(server)
    if not loopback:
        bind_to_interface(outbound, route.interface)
    if route.mark is not None:
        mark_socket(outbound, route.mark)
    if server and not loopback and not is_ip(server):
        resolve_in_core(outbound)
```

В `build_batch_probe_config` добавить параметр `route: ProbeRoute | None = None` (после
`*`), в цикле после `outbound["tag"] = outbound_tag`:

```python
        if route is not None:
            _route_past_tunnel(outbound, target.server, route)
```

и перед `return`:

```python
    config: dict[str, Any] = {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }
    if route is not None:
        direct = {"protocol": "freedom", "tag": DIRECT_TAG}
        _route_past_tunnel(direct, "", route)
        outbounds.append(direct)
        if route.dns_servers:
            config["dns"] = {
                "servers": list(route.dns_servers),
                "queryStrategy": "UseIPv4",
                "tag": PROBE_DNS_TAG,
            }
            rules.insert(
                0, {"type": "field", "inboundTag": [PROBE_DNS_TAG], "outboundTag": DIRECT_TAG}
            )
    return config
```

`_probe_batch` получает параметр `route: ProbeRoute | None` и передаёт `route=route` в оба
вызова `build_batch_probe_config` (в `accepts` и перед `BatchCore`). `probe_targets` получает
`route: ProbeRoute | None = None` и передаёт его в `_probe_batch`. `probe_profiles` получает
`route: ProbeRoute | None = None` перед `**options`, собирает
`ProbeTarget(profile.id, outbound, server=profile.bean.server_address)` и зовёт
`probe_targets(..., route=route, **options)`.

Обновить docstring модуля: «Рабочий билдер конфигурации здесь не участвует» остаётся, но
добавить: «При активном TUN пробы получают `ProbeRoute` и выходят мимо туннеля».

**Step 4: Тесты проходят**

Run: `uv run pytest tests/test_core_batch_probe.py -q && make lint`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/batch_probe.py tests/test_core_batch_probe.py
git commit -m "core: путь пробы мимо туннеля в пакетном замере"
```

---

### Task 3: Linux `netbind`: rp_filter и разбитый маршрут

**Files:**
- Modify: `src/sys/linux/netbind.py`
- Test: `tests/test_sys_netbind.py`

**Step 1: Тесты**

Фикстура и новые тесты в `tests/test_sys_netbind.py` (рядом с тестами `binding_confirmed`):

```python
@pytest.fixture
def rp_filter(tmp_path, monkeypatch):
    """Файлы /proc/sys/net/ipv4/conf/<if>/rp_filter в tmp_path; по умолчанию свободный режим."""
    monkeypatch.setattr(linux, "PROC_NET_CONF", tmp_path)

    def write(all_value: int, interface_value: int, interface: str = "eth0") -> None:
        for name, value in (("all", all_value), (interface, interface_value)):
            (tmp_path / name).mkdir(exist_ok=True)
            (tmp_path / name / "rp_filter").write_text(f"{value}\n")

    write(2, 2)
    return write


@pytest.mark.parametrize(
    ("all_value", "interface_value", "confirmed"),
    [(2, 2, True), (0, 0, True), (1, 0, False), (0, 1, False), (1, 2, True)],
)
def test_linux_strict_rp_filter_blocks_the_binding(
    monkeypatch, rp_filter, all_value, interface_value, confirmed
):
    # Действует наибольшее из all и интерфейса: 2 (свободный) перекрывает 1 (строгий).
    rp_filter(all_value, interface_value)
    route = "default via 192.0.2.1 dev eth0 metric 600\n"
    done = subprocess.CompletedProcess([], 0, stdout=route, stderr="")
    monkeypatch.setattr(linux.subprocess, "run", lambda *_a, **_k: done)

    assert linux.binding_confirmed("eth0") is confirmed


def test_linux_missing_rp_filter_counts_as_off(monkeypatch, tmp_path):
    monkeypatch.setattr(linux, "PROC_NET_CONF", tmp_path)
    route = "default via 192.0.2.1 dev eth0 metric 600\n"
    done = subprocess.CompletedProcess([], 0, stdout=route, stderr="")
    monkeypatch.setattr(linux.subprocess, "run", lambda *_a, **_k: done)

    assert linux.binding_confirmed("eth0") is True
```

Существующие `test_linux_binding_needs_a_default_route_on_the_interface` и
`test_linux_binding_is_not_confirmed_when_ip_fails` получают фикстуру `rp_filter` в параметрах
(иначе они читают настоящий `/proc`).

В параметры `test_linux_active_tunnel_comes_from_the_route` добавить случаи:

```python
        (
            "0.0.0.0/1 dev xray0 scope link\n128.0.0.0/1 dev xray0 scope link\n"
            "default via 10.0.0.1 dev eth0 metric 600\n",
            "xray0",
        ),
        ("10.0.0.0/24 dev xray0 scope link\ndefault via 10.0.0.1 dev eth0\n", None),
```

**Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_sys_netbind.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'PROC_NET_CONF'` и случай `0.0.0.0/1`
возвращает None.

**Step 3: Реализация**

В `src/sys/linux/netbind.py`:

```python
PROC_NET_CONF = Path("/proc/sys/net/ipv4/conf")


def _strict_rp_filter(interface: str) -> bool:
    """Действует наибольшее из `all` и интерфейса: 0 выключен, 1 строгий, 2 свободный."""
    values = []
    for name in ("all", interface):
        try:
            values.append(int((PROC_NET_CONF / name / "rp_filter").read_text().strip()))
        except (OSError, ValueError):
            values.append(0)
    return max(values) == 1


def binding_confirmed(interface: str) -> bool:
    """Сокету на интерфейсе есть куда идти и ответы до него дойдут.

    Маршрут: старый помощник заменял маршрут по умолчанию без метрики, и тогда у интерфейса
    своего нет. rp_filter: ответ сервера приходит на интерфейс, а лучший маршрут к серверу
    ведёт в TUN через `0.0.0.0/1`; строгий режим такой пакет отбрасывает, свободный (Ubuntu
    и systemd по умолчанию) пропускает. Только IPv4: IPv6 мимо туннеля в сеансе TUN закрыт
    таблицей `ipv6_only`.
    """
    if _strict_rp_filter(interface):
        return False
    ...  # прежняя проверка `ip route show default dev <if>`
```

`active_tunnel_interface`: команда `["ip", "-4", "route", "show"]`, в цикле пропускать строки,
не начинающиеся с `default` или `0.0.0.0/1`:

```python
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts[:1] not in (["default"], ["0.0.0.0/1"]):
            continue
        if "dev" in parts and parts.index("dev") + 1 < len(parts):
            device = parts[parts.index("dev") + 1]
            if device in tunnels:
                return device
    return None
```

Docstring модуля: заменить «пока у интерфейса есть свой маршрут по умолчанию» на «пока у
интерфейса есть свой маршрут по умолчанию и rp_filter не строгий: это проверяет
`binding_confirmed`».

**Step 4: Тесты проходят**

Run: `uv run pytest tests/test_sys_netbind.py tests/test_sys_facades.py -q && make lint`
Expected: PASS

**Step 5: Commit**

```bash
git add src/sys/linux/netbind.py tests/test_sys_netbind.py
git commit -m "sys: привязка на Linux учитывает rp_filter и разбитый маршрут"
```

---

### Task 4: Windows `netinfo` и `netbind`

**Files:**
- Modify: `src/sys/windows/netinfo.py` (SCRIPT, `Route`, `parse_snapshot`, `default_route`)
- Modify: `src/sys/windows/netbind.py` (`binding_confirmed`, `active_tunnel_interface`, docstring)
- Test: `tests/test_sys_windows_netinfo.py`, `tests/test_sys_netbind.py`

**Step 1: Тесты netinfo**

В `tests/test_sys_windows_netinfo.py`:

```python
SPLIT_ROUTE = {"alias": "xray0", "index": 40, "prefix": "0.0.0.0/1", "nexthop": "0.0.0.0",
               "metric": 0, "ifmetric": 1}  # fmt: skip


def test_routes_keep_their_prefix_and_default_to_the_whole_space():
    data = dict(SNAPSHOT, routes=[SPLIT_ROUTE, SNAPSHOT["routes"][1]])

    snapshot = netinfo.parse_snapshot(json.dumps(data))

    assert [route.prefix for route in snapshot.routes] == ["0.0.0.0/1", "0.0.0.0/0"]


def test_default_route_ignores_the_split_halves():
    # Служба ставит на TUN 0.0.0.0/1 и 128.0.0.0/1 с метрикой ниже любой физической.
    data = dict(SNAPSHOT, routes=[SPLIT_ROUTE, SNAPSHOT["routes"][1]])
    snapshot = netinfo.parse_snapshot(json.dumps(data))

    assert netinfo.default_route(snapshot).alias == "Ethernet"
```

Проверить, что `SCRIPT` собирает и половины:

```python
def test_script_collects_the_split_halves_too():
    assert "'0.0.0.0/1'" in netinfo.SCRIPT
    assert "prefix = $_.DestinationPrefix" in netinfo.SCRIPT
```

**Step 2: Тесты netbind (Windows)**

В `tests/test_sys_netbind.py` заменить `test_windows_direct_probes_stay_off_until_the_option_is_confirmed`:

```python
def _routed_snapshot(monkeypatch, routes):
    import json

    data = {
        "adapters": [
            {"alias": "Ethernet", "index": 12, "status": "Up", "description": "Intel Ethernet"},
            {"alias": "xray0", "index": 40, "status": "Up", "description": "Wintun Userspace Tunnel"},
        ],
        "ips": [],
        "dns": [],
        "routes": routes,
    }
    snapshot = netinfo.parse_snapshot(json.dumps(data))
    monkeypatch.setattr(netinfo, "snapshot", lambda: snapshot)


PHYSICAL = {"alias": "Ethernet", "index": 12, "nexthop": "192.168.0.1", "metric": 0, "ifmetric": 25}
SPLIT = {"alias": "xray0", "index": 40, "prefix": "0.0.0.0/1", "nexthop": "0.0.0.0", "metric": 0,
         "ifmetric": 1}  # fmt: skip


def test_windows_binding_is_confirmed_by_the_physical_default_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT, PHYSICAL])

    assert windows.binding_confirmed("Ethernet") is True
    assert windows.binding_confirmed("Wi-Fi") is False


def test_windows_binding_is_not_confirmed_without_a_default_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT])

    assert windows.binding_confirmed("Ethernet") is False


def test_windows_active_tunnel_is_found_by_the_split_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT, PHYSICAL])

    assert windows.active_tunnel_interface() == "xray0"


def test_windows_no_tunnel_without_split_routes(monkeypatch):
    _routed_snapshot(monkeypatch, [PHYSICAL])

    assert windows.active_tunnel_interface() is None
```

Run: `uv run pytest tests/test_sys_windows_netinfo.py tests/test_sys_netbind.py -q`
Expected: FAIL (`prefix` нет в `Route`, `binding_confirmed` всегда False, туннель не найден).

**Step 3: Реализация**

`src/sys/windows/netinfo.py`:

- В `SCRIPT` блок `routes`:

```powershell
  routes = @(Get-NetRoute -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' -or $_.DestinationPrefix -eq '0.0.0.0/1' } |
      ForEach-Object {
    $if = Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4 `
      -ErrorAction SilentlyContinue
    @{ alias = $_.InterfaceAlias; index = $_.ifIndex; prefix = $_.DestinationPrefix;
       nexthop = $_.NextHop; metric = $_.RouteMetric; ifmetric = [int]$if.InterfaceMetric } })
```

- Константы и поле:

```python
DEFAULT_PREFIX = "0.0.0.0/0"
# Половина маршрута по умолчанию, которую служба ставит на TUN: по ней виден активный туннель.
SPLIT_PREFIX = "0.0.0.0/1"


@dataclass(frozen=True)
class Route:
    alias: str
    index: int
    nexthop: str
    metric: int
    prefix: str = DEFAULT_PREFIX
```

- В `parse_snapshot`: `prefix=str(item.get("prefix") or DEFAULT_PREFIX)`.
- В `default_route`: в условие кандидатов добавить `route.prefix == DEFAULT_PREFIX`.
- Docstring модуля: «маршруты по умолчанию» → «маршруты по умолчанию и половина `0.0.0.0/1`».

`src/sys/windows/netbind.py`:

```python
"""IP_UNICAST_IF: выводит сокет пробы на нужный адаптер.

Физический маршрут по умолчанию служба не трогает (на TUN ложатся `0.0.0.0/1` и
`128.0.0.0/1`), поэтому привязка подтверждена, когда маршрут по умолчанию ведёт на адаптер.
Сама опция под настоящим TUN проверяется в `tests/integration/`.
"""


def binding_confirmed(interface: str) -> bool:
    route = netinfo.default_route(netinfo.snapshot())
    return route is not None and route.alias == interface


def active_tunnel_interface() -> str | None:
    snapshot = netinfo.snapshot()
    halves = [
        route
        for route in snapshot.routes
        if route.prefix == netinfo.SPLIT_PREFIX and netinfo.is_tunnel(snapshot.adapter(route.alias))
    ]
    if halves:
        return min(halves, key=lambda route: route.metric).alias
    # Чужой туннель, забравший маршрут по умолчанию целиком.
    whole = [route for route in snapshot.routes if route.prefix == netinfo.DEFAULT_PREFIX]
    best = min(whole, key=lambda route: route.metric, default=None)
    if best is None or not netinfo.is_tunnel(snapshot.adapter(best.alias)):
        return None
    return best.alias
```

Убрать из docstring `test_real_unicast_if_keeps_the_socket_on_the_adapter` упоминание
«открытый вопрос 5 дизайна»; оставить: «под настоящим TUN проверяет `tests/integration/`».

**Step 4: Тесты проходят**

Run: `uv run pytest tests/test_sys_windows_netinfo.py tests/test_sys_netbind.py tests/test_sys_facades.py tests/test_sys_windows_tun.py -q && make lint`
Expected: PASS

**Step 5: Commit**

```bash
git add src/sys/windows/netinfo.py src/sys/windows/netbind.py tests/test_sys_windows_netinfo.py tests/test_sys_netbind.py
git commit -m "sys: подтверждение привязки и поиск TUN на Windows по маршрутам"
```

---

### Task 5: `probe_route` и `make_batch_probe`

**Files:**
- Modify: `src/ui/logic/latency.py`
- Test: `tests/test_ui_logic_latency.py`

**Step 1: Тесты**

В `tests/test_ui_logic_latency.py` импортировать `ProbeUnavailable`, `probe_route` из
`src.ui.logic.latency` и `ProbeRoute` из `src.core.batch_probe`. Существующий
`test_make_batch_probe_measures_known_profiles_with_the_app_settings`: `fake_probe_profiles`
получает ещё `route`, `seen["route"] = route`; ожидание — `"route": None`. Новые тесты:

```python
def _context(*, running=False, mode="tun", blocked=False, tun_name="xray0"):
    state = SimpleNamespace(
        is_running=running, started_mode=mode, traffic_blocked=blocked
    )
    return SimpleNamespace(proxy_state=state, config=SimpleNamespace(tun_name=tun_name))


def _network(monkeypatch, *, interface="eth0", confirmed=True, dns=("192.168.0.1",)):
    calls: dict = {}

    def physical_interface(exclude=()):
        calls["exclude"] = tuple(exclude)
        return interface

    monkeypatch.setattr("src.ui.logic.latency.netbind.physical_interface", physical_interface)
    monkeypatch.setattr(
        "src.ui.logic.latency.netbind.binding_confirmed", lambda _iface: confirmed
    )
    monkeypatch.setattr("src.ui.logic.latency.system_dns_servers", lambda _iface: list(dns))
    return calls


def test_probe_route_is_none_outside_tun_and_without_a_block(monkeypatch):
    calls = _network(monkeypatch)

    assert probe_route(_context(running=True, mode="system")) is None
    assert probe_route(_context(running=False)) is None
    assert probe_route(SimpleNamespace()) is None
    assert calls == {}


def test_probe_route_under_tun_binds_marks_and_takes_the_network_dns(monkeypatch):
    calls = _network(monkeypatch)
    monkeypatch.setattr("src.ui.logic.latency.IS_WINDOWS", False)

    route = probe_route(_context(running=True, tun_name="tun9"))

    assert route == ProbeRoute("eth0", mark=0x7E6A, dns_servers=("192.168.0.1",))
    assert calls["exclude"] == ("tun9",)


def test_probe_route_on_windows_has_no_mark(monkeypatch):
    _network(monkeypatch, interface="Ethernet")
    monkeypatch.setattr("src.ui.logic.latency.IS_WINDOWS", True)

    assert probe_route(_context(running=True)).mark is None


def test_probe_route_while_traffic_is_blocked(monkeypatch):
    # Ядро упало под блокировкой: сеанса нет, но таблица пропускает только помеченные сокеты.
    _network(monkeypatch)
    monkeypatch.setattr("src.ui.logic.latency.IS_WINDOWS", False)

    assert probe_route(_context(running=False, blocked=True)).mark == 0x7E6A


@pytest.mark.parametrize("interface, confirmed", [(None, True), ("eth0", False)])
def test_probe_route_refuses_without_a_way_past_the_tunnel(monkeypatch, interface, confirmed):
    _network(monkeypatch, interface=interface, confirmed=confirmed)

    with pytest.raises(ProbeUnavailable, match="нет маршрута мимо туннеля"):
        probe_route(_context(running=True))


def test_make_batch_probe_reports_an_unavailable_route_and_gives_up(monkeypatch):
    def refuse(_context):
        raise ProbeUnavailable("нет маршрута")

    monkeypatch.setattr("src.ui.logic.latency.probe_route", refuse)
    probed = []
    monkeypatch.setattr("src.core.batch_probe.probe_profiles", lambda *a, **k: probed.append(1))
    reported = []

    with pytest.raises(ProbeUnavailable):
        make_batch_probe(SimpleNamespace(), on_unavailable=reported.append)([1], lambda *_: None)

    assert reported == ["нет маршрута"]
    assert probed == []


def test_make_batch_probe_hands_the_route_to_the_core(monkeypatch):
    route = ProbeRoute("eth0")
    monkeypatch.setattr("src.ui.logic.latency.probe_route", lambda _context: route)
    seen: dict = {}

    def fake_probe_profiles(profiles, *, settings, binary_path, on_result, route):
        seen["route"] = route

    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)
    context = SimpleNamespace(
        profiles=SimpleNamespace(get_profile={1: SimpleNamespace(id=1)}.get),
        config="настройки",
        xray_manager=SimpleNamespace(binary_path="/opt/xray"),
    )

    make_batch_probe(context)([1], lambda *_: None)

    assert seen["route"] is route
```

Run: `uv run pytest tests/test_ui_logic_latency.py -q`
Expected: `ImportError: cannot import name 'ProbeUnavailable'`

**Step 2: Реализация**

В `src/ui/logic/latency.py`:

```python
from src.core.batch_probe import ProbeRoute
from src.core.platform_info import IS_WINDOWS
from src.sys import netbind
from src.sys.firewall_policy import SOCKET_MARK
from src.sys.resolver import system_dns_servers

PROBE_UNAVAILABLE = "Замер при активном TUN недоступен: нет маршрута мимо туннеля"


class ProbeUnavailable(RuntimeError):
    """Замер сейчас невозможен; текст показывается пользователю."""


def probe_route(context: Any) -> ProbeRoute | None:
    """Путь проб мимо туннеля: при TUN и при заблокированном трафике, иначе None.

    Зовётся из потока замера, а не из контроллера: на Windows поиск интерфейса — снимок сети
    через PowerShell, в главном потоке он подвесил бы окно.
    """
    state = getattr(context, "proxy_state", None)
    if state is None:
        return None
    in_tun = state.is_running and state.started_mode == "tun"
    if not in_tun and not getattr(state, "traffic_blocked", False):
        return None

    tun_name = (getattr(context.config, "tun_name", "") or "xray0").strip()
    interface = netbind.physical_interface(exclude=(tun_name,))
    if interface is None or not netbind.binding_confirmed(interface):
        raise ProbeUnavailable(PROBE_UNAVAILABLE)
    return ProbeRoute(
        interface=interface,
        mark=None if IS_WINDOWS else SOCKET_MARK,
        dns_servers=tuple(system_dns_servers(interface)),
    )


def make_batch_probe(
    context: Any, on_unavailable: Callable[[str], None] | None = None
) -> BatchProbeFn:
    """Batch probe bound to the application context.

    Контекст читается в момент замера, а не при создании: список профилей, настройки и
    режим сеанса к этому времени могли измениться. `on_unavailable` получает текст отказа,
    когда пути мимо туннеля нет; профили при этом получают -1 от `LatencyRunner`.
    """

    def batch_probe(profile_ids: list[int], emit: ResultFn) -> None:
        from src.core.batch_probe import probe_profiles

        try:
            route = probe_route(context)
        except ProbeUnavailable as e:
            if on_unavailable is not None:
                on_unavailable(str(e))
            raise

        found = (context.profiles.get_profile(profile_id) for profile_id in profile_ids)
        probe_profiles(
            [profile for profile in found if profile is not None],
            settings=context.config,
            binary_path=context.xray_manager.binary_path,
            on_result=emit,
            route=route,
        )

    return batch_probe
```

Прежняя проверка `started_mode == "tun"` с `RuntimeError` удаляется. Docstring модуля:
добавить, что модуль не импортирует GTK, но импортирует `src.sys` (фасады без тулкита).

**Step 3: Тесты проходят**

Run: `uv run pytest tests/test_ui_logic_latency.py tests/test_ui_platform_branches.py -q && make lint`
Expected: PASS. Если `test_ui_platform_branches` возражает против `IS_WINDOWS` в
`src/ui/logic/latency.py`, добавить модуль в его список допустимых мест с пометкой «метка
сокета нужна только на Linux».

**Step 4: Commit**

```bash
git add src/ui/logic/latency.py tests/test_ui_logic_latency.py
git commit -m "ui: путь замера мимо туннеля при TUN и блокировке"
```

---

### Task 6: Контроллер

**Files:**
- Modify: `src/ui/controller.py:936-955` (`_ensure_latency_runner`, `_can_probe`)
- Test: `tests/test_ui_controller.py:959-967`

**Step 1: Тесты**

Заменить `test_probe_is_refused_while_tun_is_active`:

```python
def _no_route(_context):
    from src.ui.logic.latency import ProbeUnavailable

    raise ProbeUnavailable("нет маршрута")


def test_probe_under_tun_without_a_route_toasts_and_marks_everything_dead(made, monkeypatch):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.context.proxy_state.set_running(entry.id, mode="tun")
    monkeypatch.setattr("src.ui.logic.latency.probe_route", _no_route)

    controller.test_latency_for(entry.id)
    controller.latency_runner.wait(5)

    assert ("нет маршрута", None, None) in shell.toasts
    assert controller.context.profiles.get_profile(entry.id).latency_ms == -1
    assert controller.latency_runner.last_run_complete is False


def test_probe_under_tun_with_a_route_measures(made, monkeypatch):
    from src.core.batch_probe import ProbeRoute

    controller, shell, _ = made
    entry = add_profile(controller)
    controller.context.proxy_state.set_running(entry.id, mode="tun")
    monkeypatch.setattr("src.ui.logic.latency.probe_route", lambda _c: ProbeRoute("eth0"))

    def fake_probe_profiles(profiles, *, settings, binary_path, on_result, route):
        assert route == ProbeRoute("eth0")
        for profile in profiles:
            on_result(profile.id, 42)

    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)

    controller.test_latency_for(entry.id)
    controller.latency_runner.wait(5)

    assert controller.context.profiles.get_profile(entry.id).latency_ms == 42
    assert all(not text.startswith("Замер при активном TUN") for text, *_ in shell.toasts)
```

Если `latency_ms` в контроллере обновляется иначе (посмотреть `_on_latency_result`), подправить
проверку по месту; суть — профиль получил -1 и 42 соответственно.

Run: `uv run pytest tests/test_ui_controller.py -k "probe_under_tun" -q`
Expected: FAIL — тост «Замер при активном TUN недоступен: независимый маршрут…», замер не
запускается.

**Step 2: Реализация**

В `src/ui/controller.py`:

```python
    def _ensure_latency_runner(self) -> LatencyRunner:
        if self.latency_runner is None:
            if self._latency_probe is not None:
                self.latency_runner = LatencyRunner(
                    self._latency_probe, dispatch=self._loop.dispatch
                )
            else:
                # Весь набор меряет один временный процесс ядра. Отказ пути мимо
                # туннеля приходит из потока замера: тост — через главный цикл.
                self.latency_runner = LatencyRunner(
                    batch_probe=make_batch_probe(
                        self.context,
                        on_unavailable=lambda text: self._loop.dispatch(self.toast, text),
                    ),
                    dispatch=self._loop.dispatch,
                )
        return self.latency_runner

    def _can_probe(self) -> bool:
        if self._subscription_busy:
            self.toast("Дождитесь обновления подписок")
            return False
        return True
```

Импорт `ProxyMode` внутри `_can_probe` больше не нужен.

**Step 3: Тесты проходят**

Run: `uv run pytest tests/test_ui_controller.py tests/test_ui_logic_latency.py -q && make lint`
Expected: PASS

**Step 4: Commit**

```bash
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "ui: разрешить замер при активном TUN"
```

---

### Task 7: Помощник: разбитый маршрут и `release`

**Files:**
- Modify: `core/scripts/tun_route_helper.sh`
- Test: `tests/test_sys_tun_helper_script.py`

**Step 1: Тесты**

Заменить `test_apply_with_valid_arguments_runs_ip` и добавить тесты `release`:

```python
def test_apply_keeps_the_default_route_and_splits_it_on_the_tun(fakebin, tmp_path):
    result, log = run_helper(
        fakebin, tmp_path, "apply", "xray0", "1.2.3.4", "10.0.0.1", "eth0", "600"
    )

    assert result.returncode == 0, result.stderr
    assert log.splitlines() == [
        "ip route replace 1.2.3.4/32 via 10.0.0.1 dev eth0",
        "ip route replace 0.0.0.0/1 dev xray0",
        "ip route replace 128.0.0.0/1 dev xray0",
    ]


def test_apply_without_a_gateway_routes_the_proxy_by_device(fakebin, tmp_path):
    _result, log = run_helper(fakebin, tmp_path, "apply", "xray0", "1.2.3.4", "-", "eth0", "-")

    assert "ip route replace 1.2.3.4/32 dev eth0" in log
    assert "default" not in log


def test_release_removes_only_the_tun_halves_and_the_proxy_route(fakebin, tmp_path):
    result, log = run_helper(fakebin, tmp_path, "release", "xray0", "1.2.3.4")

    assert result.returncode == 0, result.stderr
    assert log.splitlines() == [
        "ip route del 0.0.0.0/1 dev xray0",
        "ip route del 128.0.0.0/1 dev xray0",
        "ip route del 1.2.3.4/32",
    ]


def test_release_survives_routes_that_are_already_gone(fakebin, tmp_path):
    # После падения ядра TUN исчез вместе с маршрутами: `ip route del` отвечает ошибкой.
    _fake(fakebin, "ip", 'echo "ip $*" >> "$FAKE_LOG"; exit 2')

    result, log = run_helper(fakebin, tmp_path, "release", "xray0", "1.2.3.4")

    assert result.returncode == 0
    assert len(log.splitlines()) == 3


@pytest.mark.parametrize(
    "args",
    [("xray0",), ("xray0\nflush", "1.2.3.4"), ("xray0", "1.2.3"), ("xray0", "1.2.3.4", "x")],
)
def test_release_refuses_bad_arguments(fakebin, tmp_path, args):
    result, log = run_helper(fakebin, tmp_path, "release", *args)

    assert result.returncode == 1
    assert log == ""


def test_restore_still_returns_the_replaced_default_route(fakebin, tmp_path):
    # Журнал сеанса старой версии: маршрут по умолчанию был заменён и его нужно вернуть.
    _result, log = run_helper(fakebin, tmp_path, "restore", "1.2.3.4", "10.0.0.1", "eth0", "600")

    assert "ip route replace default via 10.0.0.1 dev eth0 metric 600" in log
    assert "ip route del 1.2.3.4/32" in log
```

`test_features_lists_the_firewall` дополнить: `assert "split" in result.stdout.split()`.

Run: `uv run pytest tests/test_sys_tun_helper_script.py -q`
Expected: FAIL — `apply` пишет `default`, `release` — `unknown action`.

**Step 2: Реализация**

В `core/scripts/tun_route_helper.sh`: в шапке Usage добавить строку
`#   tun-route-helper release <tun_name> <proxy_ip>` и пояснение:

```sh
# apply: маршрут по умолчанию не трогается, на TUN ложатся две половины 0.0.0.0/1 и
# 128.0.0.0/1 — они длиннее любого /0 и выигрывают у него, а физический маршрут
# остаётся для сокетов, привязанных к интерфейсу. restore возвращает маршрут,
# заменённый помощником старой версии: журнал упавшего сеанса переживает обновление.
```

В `apply` заменить `ip route replace default dev "$tun_name"` на:

```sh
    ip route replace 0.0.0.0/1 dev "$tun_name"
    ip route replace 128.0.0.0/1 dev "$tun_name"
```

Параметр `metric` в `apply` остаётся ради прежней сигнатуры (проверяется, не используется).

После `restore)` добавить:

```sh
  release)
    [ $# -eq 2 ] || die "release requires 2 args"
    tun_name="$1"
    proxy_ip="$2"

    is_ifname "$tun_name" || die "invalid tun_name"
    is_ipv4 "$proxy_ip" || die "invalid proxy_ip"

    # Маршрутов может уже не быть: TUN упавшего ядра уносит свои с собой.
    ip route del 0.0.0.0/1 dev "$tun_name" >/dev/null 2>&1 || true
    ip route del 128.0.0.0/1 dev "$tun_name" >/dev/null 2>&1 || true
    ip route del "$proxy_ip/32" >/dev/null 2>&1 || true
    ;;
```

`features`: `echo "apply restore release split dns firewall"`.

**Step 3: Тесты проходят**

Run: `uv run pytest tests/test_sys_tun_helper_script.py -q`
Expected: PASS

**Step 4: Commit**

```bash
git add core/scripts/tun_route_helper.sh tests/test_sys_tun_helper_script.py
git commit -m "tun: разбитый маршрут по умолчанию вместо замены"
```

---

### Task 8: `tun_route.py`: журнал двух схем

**Files:**
- Modify: `src/sys/linux/tun_route.py`
- Modify: `src/sys/linux/tun_access.py:43-54` (импорт `_helper_features` из `tun_route`)
- Test: `tests/test_sys_tun_route.py`, `tests/test_sys_tun_access.py`

**Step 1: Тесты**

В `tests/test_sys_tun_route.py` расширить `FakeSystem`:

```python
class FakeSystem:
    """`ip` и помощник без настоящей системы: таблица — одна строка default."""

    def __init__(self, default: str = DEFAULT_WIFI, *, fail_apply=False, fail_restore=False):
        self.default = default
        self.fail_apply = fail_apply
        self.fail_restore = fail_restore
        self.split = False  # помощник умеет разбитый маршрут
        self.calls: list[tuple] = []
        self.journal_on_apply: list[dict] | None = None

    def run_helper(self, action, args, timeout=15):
        self.calls.append(("helper", action, args))
        if action == "apply":
            self.journal_on_apply = tun_route._journal().entries()
            if self.fail_apply:
                return False, "denied"
            if not self.split:
                self.default = f"default dev {args[0]} scope link"
        if action in ("restore", "release"):
            if self.fail_restore:
                return False, "denied"
            if action == "restore":
                gateway, dev = args[1], args[2]
                self.default = f"default via {gateway} dev {dev}"
        return True, ""

    def releases(self):
        return [call for call in self.calls if call[:2] == ("helper", "release")]
```

В фикстуре `system` добавить `monkeypatch.setattr(tun_route, "_split_supported", lambda: fake.split)`.
Новые тесты:

```python
# --- разбитый маршрут ---


@pytest.fixture
def split(system):
    system.split = True
    return system


def test_split_apply_records_a_release_entry_and_keeps_the_default_route(split):
    ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert ok
    assert state.split is True
    assert split.journal_on_apply == [
        {"op": "route.release", "tun_name": "xray0", "proxy_ip": "8.8.8.8"}
    ]
    # Аргументы помощника прежние: старый помощник их тоже принимает.
    assert ("helper", "apply", ["xray0", "8.8.8.8", "192.168.0.1", "wlp1s0", "600"]) in split.calls
    assert split.default == DEFAULT_WIFI


def test_split_restore_releases_and_never_touches_the_default_route(split):
    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert tun_route.restore_tun_routes(state) == (True, "")

    assert split.releases() == [("helper", "release", ["xray0", "8.8.8.8"])]
    assert split.restores() == []
    assert tun_route._journal().entries() == []


def test_split_recover_releases_even_when_the_network_changed(split):
    # TUN упавшего сеанса исчез вместе со своими маршрутами; остаётся /32, а
    # маршрут по умолчанию и так живой — возвращать его нельзя.
    tun_route.apply_tun_routes("xray0", "8.8.8.8")
    split.default = "default via 10.0.0.1 dev enp3s0"
    split.calls.clear()

    assert tun_route.recover_tun_routes() == (True, "")

    assert split.releases() == [("helper", "release", ["xray0", "8.8.8.8"])]
    assert split.restores() == []
    assert tun_route._journal().entries() == []


def test_split_failed_release_keeps_the_journal(split):
    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")
    split.fail_restore = True

    ok, _ = tun_route.restore_tun_routes(state)

    assert not ok
    assert tun_route._journal().entries()[-1]["op"] == "route.release"


def test_old_journal_entry_is_still_restored_by_the_new_code(split):
    # Сеанс старой версии упал, пакет обновился: маршрут по умолчанию всё ещё в TUN.
    tun_route.JOURNAL_FILE.write_text(
        json.dumps(
            [
                {
                    "op": "route.restore",
                    "tun_name": "xray0",
                    "proxy_ip": "8.8.8.8",
                    "gateway": "192.168.0.1",
                    "dev": "wlp1s0",
                    "metric": "600",
                }
            ]
        )
    )
    split.default = "default dev xray0 scope link"

    assert tun_route.recover_tun_routes() == (True, "")

    assert split.restores() == [("helper", "restore", ["8.8.8.8", "192.168.0.1", "wlp1s0", "600"])]


def test_split_fallback_without_helper_uses_the_same_routes(split, monkeypatch):
    commands = []

    def batch(cmds, timeout=20):
        commands.extend(cmds)
        return True, ""

    monkeypatch.setattr(tun_route, "_run_helper", lambda *_a, **_k: (False, "helper not installed"))
    monkeypatch.setattr(tun_route, "_run_ip_batch_privileged", batch)

    ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert ok and state.split
    assert commands == [
        ["route", "replace", "8.8.8.8/32", "via", "192.168.0.1", "dev", "wlp1s0"],
        ["route", "replace", "0.0.0.0/1", "dev", "xray0"],
        ["route", "replace", "128.0.0.0/1", "dev", "xray0"],
    ]
```

В параметры `test_journal_rejects_entries_outside_the_schema` добавить
`{"op": "route.release", "tun_name": "xray0"}` (нет `proxy_ip`) и
`{"op": "route.release", "tun_name": "x y", "proxy_ip": "8.8.8.8"}`. Отдельный тест:

```python
def test_journal_accepts_a_release_entry(system):
    entry = {"op": "route.release", "tun_name": "xray0", "proxy_ip": "8.8.8.8"}
    tun_route.JOURNAL_FILE.write_text(json.dumps([entry]))

    assert tun_route._journal().entries() == [entry]
```

Тест `_split_supported`:

```python
def test_split_is_supported_by_a_new_helper_or_without_any(monkeypatch):
    monkeypatch.setattr(tun_route.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(tun_route, "_helper_features", lambda: {"apply", "split"})
    assert tun_route._split_supported() is True
    monkeypatch.setattr(tun_route, "_helper_features", lambda: {"apply"})
    assert tun_route._split_supported() is False
    monkeypatch.setattr(tun_route.os.path, "exists", lambda _p: False)
    assert tun_route._split_supported() is True
```

В `tests/test_sys_tun_access.py` тесты `_helper_features` остаются как есть: имя
импортируется в `tun_access` из `tun_route`, а подмена `subprocess.run` глобальна.

Run: `uv run pytest tests/test_sys_tun_route.py tests/test_sys_tun_access.py -q`
Expected: FAIL — нет `_split_supported`, `state.split`, записи `route.release`.

**Step 2: Реализация**

В `src/sys/linux/tun_route.py`:

```python
SPLIT_DEFAULT = ("0.0.0.0/1", "128.0.0.0/1")

# Журнал маршрутов, которые нужно убрать или вернуть. Переживает падение
# приложения. Новый помощник кладёт на TUN половины SPLIT_DEFAULT, а маршрут по
# умолчанию не трогает: ядро умирает вместе с TUN, половины исчезают с ним, и
# остаётся снять /32 (запись `route.release`). Старый помощник заменял маршрут по
# умолчанию, и его нужно вернуть (`route.restore`): такая запись бывает после
# обновления пакета поверх упавшего сеанса и при старом помощнике у приложения из
# исходников.
JOURNAL_FILE: Path = CORE_DIR / "tun-route-journal.json"


@dataclass
class TunRouteState:
    """State required to restore system routes after TUN session."""

    default_gateway: str | None
    default_dev: str
    default_metric: str | None
    proxy_ip: str
    tun_name: str
    # Разбитый маршрут: откат убирает половины и /32, маршрут по умолчанию не трогает.
    split: bool = False


def _valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("op") == "route.release":
        return _IFNAME.fullmatch(str(entry.get("tun_name", ""))) is not None and _is_ipv4(
            entry.get("proxy_ip")
        )
    if entry.get("op") != "route.restore":
        return False
    ...  # прежняя проверка


def _journal_entry(state: TunRouteState) -> dict:
    if state.split:
        return {"op": "route.release", "tun_name": state.tun_name, "proxy_ip": state.proxy_ip}
    return {...}  # прежняя запись


def _state_from_entry(entry: dict) -> TunRouteState:
    if entry["op"] == "route.release":
        return TunRouteState(
            default_gateway=None,
            default_dev="",
            default_metric=None,
            proxy_ip=entry["proxy_ip"],
            tun_name=entry["tun_name"],
            split=True,
        )
    ...  # прежняя


def _helper_features() -> set[str]:
    """Что умеет установленный помощник; у старого такого действия нет."""
    ok, out, _err = _run_command(["sudo", "-n", HELPER_PATH, "features"], timeout=5)
    return set(out.split()) if ok else set()


def _split_supported() -> bool:
    """Разбитый маршрут ставит новый помощник; без помощника — сами команды `ip`."""
    return not os.path.exists(HELPER_PATH) or "split" in _helper_features()
```

В `apply_tun_routes` после вычисления `proxy_ip`:

```python
    split = _split_supported()
    state = TunRouteState(..., split=split)
    ...
    ok, err = _run_helper("apply", helper_args)
    if not ok:
        if split:
            tun_routes = [["route", "replace", prefix, "dev", tun_name] for prefix in SPLIT_DEFAULT]
        else:
            tun_routes = [["route", "replace", "default", "dev", tun_name]]
        ok, err = _run_ip_batch_privileged([route_proxy_args, *tun_routes])
    ...
    logger.info(
        "TUN routes applied: %s->%s, proxy %s via %s",
        "0/1+128/1" if split else "default", tun_name, proxy_ip, dev,
    )
```

`restore_tun_routes`:

```python
def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    """Restore system routes after TUN session."""
    if state is None:
        return True, ""
    if state.split:
        return _release_tun_routes(state)
    ...  # прежний код


def _release_tun_routes(state: TunRouteState) -> tuple[bool, str]:
    ok, err = _run_helper("release", [state.tun_name, state.proxy_ip])
    if not ok and err != HELPER_MISSING:
        return False, f"Cannot release TUN routes: {err}"
    if not ok:
        # Без помощника: каждый маршрут отдельно, отсутствующий — не ошибка.
        for prefix in SPLIT_DEFAULT:
            _run_ip_privileged(["route", "del", prefix, "dev", state.tun_name])
        _run_ip_privileged(["route", "del", f"{state.proxy_ip}/32"])
    _journal().clear()
    logger.info("TUN routes released: %s", state.tun_name)
    return True, ""
```

`recover_tun_routes`: сразу после `state = _state_from_entry(entries[-1])`:

```python
    if state.split:
        logger.warning("Removing routes left by a crashed TUN session")
        return restore_tun_routes(state)
```

Docstring `recover_tun_routes` дополнить: «Для разбитого маршрута проверка не нужна: половины
исчезли вместе с TUN, снимается только `/32`».

В `src/sys/linux/tun_access.py`: удалить `_helper_features`, импортировать
`from src.sys.linux.tun_route import HELPER_PATH, _helper_features`.

**Step 3: Тесты проходят**

Run: `uv run pytest tests/test_sys_tun_route.py tests/test_sys_tun_access.py tests/test_core_connection.py tests/test_sys_facades.py -q && make lint`
Expected: PASS (если `tests/test_core_connection.py` называется иначе, взять тесты
`ConnectionService` по `grep -l restore_tun_routes tests/*.py`).

**Step 4: Commit**

```bash
git add src/sys/linux/tun_route.py src/sys/linux/tun_access.py tests/test_sys_tun_route.py
git commit -m "tun: журнал разбитого маршрута и откат старой схемы"
```

---

### Task 9: Документация и комментарии

**Files:**
- Modify: `CLAUDE.md:219-222`
- Modify: `docs/plans/2026-11-03-tun-kill-switch-design.md:11-15`
- Modify: `src/diag/network.py` (комментарий у `binding_confirmed`, если упоминает замену маршрута)

**Step 1: CLAUDE.md**

Абзац «TUN на Linux»: «маршрут по умолчанию переключает помощник» → «маршруты в TUN
(`0.0.0.0/1` и `128.0.0.0/1`, маршрут по умолчанию не трогается) ставит помощник». Добавить
предложение: «Замер задержки при TUN и при заблокированном трафике идёт мимо туннеля:
`probe_route` в `src/ui/logic/latency.py` привязывает пробное ядро к физическому интерфейсу;
дизайн: `docs/plans/2026-11-07-tun-latency-probe-design.md`.»

**Step 2: Дизайн kill switch**

К пункту «Падение xray в TUN» добавить: «2026-11-07: помощник больше не заменяет маршрут по
умолчанию, а кладёт на TUN `0.0.0.0/1` и `128.0.0.0/1`; после падения ядра они исчезают вместе
с интерфейсом в любой сети, утечку закрывает только блокировка трафика. См.
`2026-11-07-tun-latency-probe-design.md`.»

**Step 3: Проверить упоминания**

Run: `grep -rn "replace default\|заменяет маршрут\|без метрики" src docs/plans/2026-11-05-network-diagnostics-desktop-design.md CLAUDE.md`
Каждое совпадение в `src` — либо `restore` для старой схемы (оставить), либо устаревший
комментарий (поправить).

**Step 4: Commit**

```bash
git add CLAUDE.md docs/plans/2026-11-03-tun-kill-switch-design.md src
git commit -m "docs: разбитый маршрут TUN и замер мимо туннеля"
```

---

### Task 10: Лаборатория QEMU

**Files:**
- Modify: `tests/vm/guest/lab.py:209-218` (`tun_is_default`, `uplink_is_default`)
- Modify: `tests/vm/guest/lab_servers.py:38-50` (`Echo.do_HEAD`)
- Modify: `tests/vm/guest/checks.py` (сценарии замера, docstring теста без физического маршрута)

**Step 1: Лаборатория**

`lab.py`:

```python
def split_routes() -> str:
    return sh("ip", "route", "show", "0.0.0.0/1").stdout + sh("ip", "route", "show", "128.0.0.0/1").stdout


def tun_is_default() -> bool:
    """Трафик идёт в TUN: обе половины маршрута по умолчанию лежат на нём."""
    halves = split_routes().splitlines()
    return len(halves) == 2 and all(f"dev {TUN}" in half for half in halves)


def uplink_is_default() -> bool:
    return (
        f"via {GATEWAY} dev uplink0" in default_route()
        and not tun_is_default()
        and f"dev {TUN}" not in default_route()
    )
```

`lab_servers.py`, в `Echo`:

```python
    def do_HEAD(self) -> None:
        # Замер задержки шлёт HEAD: отвечаем так же, но без тела.
        source = client_address(self.client_address[0])
        write_log("echo.jsonl", src=source, path=self.path)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
```

**Step 2: Сценарии**

В `checks.py` (импорт `direct_hits`, `EXIT_B`, `DIRECT` уже есть; добавить `wait_until`,
если нет):

```python
# --- замер задержки ---

PROBE_PATH = "/generate_204"


def probe_sources() -> set[str]:
    return {e["src"] for e in lab.read_log("echo.jsonl") if e["path"].startswith(PROBE_PATH)}


def measure_all(app: Application) -> None:
    """Замер всех серверов: ждём, пока пробы обоих серверов дойдут до сайта."""
    lab.clear_logs()
    app.action("test-latency")
    wait_until(lambda: probe_sources() >= {EXIT_A, EXIT_B}, "пробы A и B дошли до сайта", timeout=40)


def assert_b_was_probed_past_the_tunnel() -> None:
    # Имя сервера B спрашивается у DNS сети с настоящего адреса, а не через сервер A.
    sources = set(dns_sources("b.veblock.test"))
    assert DIRECT in sources, f"Имя B разрешалось не напрямую: {sources}"
    assert EXIT_A not in sources, "Имя B ушло в туннель через A"


def test_latency_under_tun_is_measured_past_the_tunnel(app):
    app.connect("A", EXIT_A)
    assert tun_is_default()

    measure_all(app)

    assert_b_was_probed_past_the_tunnel()
    # Сеанс не задет.
    assert lab.try_get(SITE) == EXIT_A
    assert tun_is_default()


def test_latency_under_the_block_is_measured_past_the_tunnel(guarded):
    guarded.connect("A", EXIT_A)

    measure_all(guarded)

    assert_b_was_probed_past_the_tunnel()
    assert lab.try_get(SITE) == EXIT_A


def test_latency_while_traffic_is_blocked_still_reaches_the_servers(guarded):
    # Ядро упало, таблица закрыта: пробы помечены и проходят, сайт напрямую — нет.
    guarded.connect("A", EXIT_A)
    crash_until_blocked(guarded)
    guarded.wait_state("трафик заблокирован")

    measure_all(guarded)

    assert_b_was_probed_past_the_tunnel()
    assert lab.try_get(SITE) is None
```

Если `wait_state` ждёт другой текст состояния BLOCKED, взять его из
`test_second_crash_blocks_and_reconnect_returns_to_the_same_server`.

Docstring `test_diagnostics_without_a_physical_route_does_not_blame_the_network` заменить на:
«Без маршрута по умолчанию на физическом интерфейсе выйти мимо туннеля некуда.»

Также проверить `test_tun_session_closes_ipv6_and_disconnect_undoes_everything` и соседей: они
ждут `uplink_is_default` после отключения — с новыми функциями это по-прежнему верно.

**Step 3: Запуск**

Run: `make test-vm` (полный прогон, около получаса; сеть хоста не трогает).
Expected: все сценарии зелёные, включая прежние про маршруты и диагностику. Журналы —
`/var/tmp/veblock-vm/results-*`.

Если падает только замер: смотреть `echo.jsonl`, `dns.jsonl` и лог приложения в результатах;
типичные причины — `rp_filter` в гостевой системе (проверить `sysctl net.ipv4.conf.all.rp_filter`,
ожидается 2), отсутствие метки на пробах (`nft list table inet veblock` счётчики reject).

**Step 4: Commit**

```bash
git add tests/vm/guest/lab.py tests/vm/guest/lab_servers.py tests/vm/guest/checks.py
git commit -m "test-vm: замер задержки при TUN и блокировке"
```

---

### Task 11: Windows: проверка на живой системе

**Files:**
- Modify: `tests/test_sys_netbind.py` (маркер `windows`)
- Modify: `tests/integration/test_service_windows.py`

**Step 1: Без TUN**

Рядом с `test_real_unicast_if_keeps_the_socket_on_the_adapter`:

```python
@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="нужна настоящая Windows")
def test_real_binding_is_confirmed_on_the_physical_adapter():
    interface = windows.physical_interface()
    if interface is None:
        pytest.skip("нет сети")
    assert windows.binding_confirmed(interface) is True
```

**Step 2: Под TUN**

В `tests/integration/test_service_windows.py` после `test_tun_session_and_rollback` (повторить
его подготовку сеанса, посмотреть фикстуру `client`):

```python
def test_binding_is_confirmed_under_tun_and_probe_goes_past_it(client):
    """Служба кладёт на TUN 0.0.0.0/1 и 128.0.0.0/1; физический маршрут остаётся."""
    from src.sys.windows import netbind, netinfo

    with tun_session(client):  # контекст из test_tun_session_and_rollback, вынести если нужно
        netinfo._cached = None
        interface = netbind.physical_interface(exclude=("xray0",))
        assert interface is not None
        assert netbind.binding_confirmed(interface) is True
        assert netbind.active_tunnel_interface() == "xray0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            netbind.socket_binder(interface)(sock)
            sock.connect(("192.0.2.1", 9))
            assert sock.getsockname()[0] in netbind.interface_addresses(interface)
```

Эти тесты запускаются в CI `.github/workflows/windows.yml`; локально на Linux они
пропускаются. Результат CI — единственное подтверждение `IP_UNICAST_IF` под разбитым
маршрутом: если тест под TUN падает, в дизайне это открытый вопрос, и `binding_confirmed`
на Windows возвращается к `False` до разбора.

**Step 3: Commit**

```bash
git add tests/test_sys_netbind.py tests/integration/test_service_windows.py
git commit -m "test: привязка под TUN на живой Windows"
```

---

### Task 12: Финальная проверка

Run:

```bash
make lint
uv run pytest -q
make test-gtk
make test-qt
```

Expected: всё зелёное. Затем `git log --oneline develop ^master` — список коммитов задачи, и
по skill superpowers:finishing-a-development-branch решить, как интегрировать.
