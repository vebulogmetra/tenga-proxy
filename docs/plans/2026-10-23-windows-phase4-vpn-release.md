# Фаза 4. VPN-режимы, обновления, документация, релиз — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Контекст: `docs/plans/2026-10-23-windows-port-design.md` (раздел «VPN-режимы»),
> дорожная карта `docs/plans/2026-10-23-windows-port-plan.md`.
> Предыдущая фаза: `docs/plans/2026-10-23-windows-phase3-service-tun.md`.

**Goal:** Паритет с Linux: режимы `VPN_WITH_*` работают со встроенными VPN Windows и WireGuard, уведомление об обновлении находит установщик, тексты интерфейса не упоминают Linux-специфику на Windows, установщик публикуется в релиз, документация описывает Windows.

**Architecture:** `src/sys/windows/vpn.py` получает реальную реализацию поверх двух источников: встроенные VPN (`Get-VpnConnection` для списка и состояния, `rasdial` для подключения — без прав администратора) и туннели WireGuard (список и управление — через службу, потому что каталог конфигураций WireGuard доступен только SYSTEM). Интерфейс, IP и DNS VPN берутся из снимка сети, который начинает видеть RAS-интерфейсы, не попадающие в `Get-NetAdapter`. Платформенные тексты UI выносятся в GTK-независимую логику.

**Tech Stack:** PowerShell `VpnClient` (`Get-VpnConnection`), `rasdial.exe`, `wireguard.exe /installtunnelservice` и `/uninstalltunnelservice`, GitHub Actions + `gh release`.

---

## Принятые решения

- **Список встроенных VPN — `Get-VpnConnection`**, а не разбор phonebook-файлов:
  он отдаёт и пользовательские, и общие (`-AllUserConnection`) подключения, а
  `ConnectionStatus` не переводится на язык системы. Подключение — `rasdial
  "<имя>"` с сохранёнными учётными данными; его вывод переведён, поэтому
  смотрим только код возврата.
- **WireGuard — через службу.** Конфигурации WireGuard для Windows лежат в
  `%ProgramFiles%\WireGuard\Data\Configurations\*.conf.dpapi` и читаются только
  SYSTEM; служба туннеля существует, пока туннель активен. Поэтому список,
  подъём и опускание — команды службы `wireguard.list/up/down`. Состояние
  читает GUI сам: `Get-Service 'WireGuardTunnel$<имя>'` доступен пользователю.
- **Одно поле «Имя подключения»** для обоих видов, как на Linux. Сначала
  ищется встроенный VPN, затем туннель WireGuard. Совпадение имён — встроенный
  выигрывает (отражается в документации).
- **OpenVPN и прочие клиенты** не управляются: если их адаптер поднят и имя
  совпадает с введённым, профиль использует его интерфейс, но подключать и
  отключать его приложение не может (`connect_vpn` вернёт False с записью в
  лог) — как на Linux для подключений вне NetworkManager.
- **Публикация в релиз** — при пуше тега `v*`: установщик прикрепляется к
  релизу GitHub (создаётся черновик, если релиза ещё нет). AppImage
  по-прежнему собирается и публикуется вручную, как сейчас.

---

### Task 4.0: Сверка с кодом и с WireGuard

**Step 1:** Фаза 3 выполнена, приёмка пройдена (раздел «Статус» фазы 3).

**Step 2:** Перечитать `src/sys/windows/vpn.py` (заглушки фазы 1),
`src/sys/windows/netinfo.py`, `src/winsvc/protocol.py` (`COMMANDS`),
`src/winsvc/dispatch.py` (`ROUTES`), `src/core/connection.py`
(`_auto_connect_vpn`, `_auto_disconnect_vpn`), `src/core/config_builder.py`
(использование `get_vpn_interface`, `get_vpn_dns_servers`, `is_vpn_active`),
`src/core/app_update.py`, `src/ui/dialogs/profile_routing.py` (группа VPN),
`src/ui/dialogs/settings.py` (текст про AppImage).

**Step 3 (владелец, на VM):** проверить, что
`& "$env:ProgramFiles\WireGuard\wireguard.exe" /installtunnelservice "$env:ProgramFiles\WireGuard\Data\Configurations\<имя>.conf.dpapi"`
от администратора поднимает туннель, а `/uninstalltunnelservice <имя>` его
опускает. Если `.conf.dpapi` не принимается, задачу 4.3 сузить до
управления уже установленными службами туннелей (`sc start/stop`), а в UI
написать, что туннель нужно один раз активировать в WireGuard. Записать
результат в «Статус».

---

### Task 4.1: RAS-интерфейсы в снимке сети

Интерфейсы PPP встроенных VPN не возвращаются `Get-NetAdapter`, но есть у
`Get-NetIPAddress` и `Get-DnsClientServerAddress` с `InterfaceAlias`, равным
имени подключения. Сейчас `parse_snapshot` такие адреса отбрасывает.

**Files:**
- Modify: `src/sys/windows/netinfo.py` (скрипт: `index` в `ips`; разбор; `Adapter.listed`; `is_tunnel`)
- Test: `tests/test_sys_windows_netinfo.py`

**Step 1: Write the failing tests**

```python
def test_ip_only_interfaces_become_unlisted_adapters():
    data = dict(
        SNAPSHOT,
        ips=[*SNAPSHOT["ips"], {"alias": "Work VPN", "ip": "10.9.0.2", "index": 55}],
        dns=[*SNAPSHOT["dns"], {"alias": "Work VPN", "servers": ["10.9.0.1"]}],
    )

    adapter = netinfo.parse_snapshot(json.dumps(data)).adapter("Work VPN")

    assert adapter.ipv4 == ["10.9.0.2"]
    assert adapter.dns == ["10.9.0.1"]
    assert adapter.index == 55
    assert adapter.listed is False


def test_unlisted_adapters_are_tunnels():
    data = dict(SNAPSHOT, ips=[{"alias": "Work VPN", "ip": "10.9.0.2", "index": 55}])

    assert netinfo.is_tunnel(netinfo.parse_snapshot(json.dumps(data)).adapter("Work VPN"))
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_netinfo.py -v --no-cov`
Expected: FAIL — адаптера `Work VPN` нет

**Step 3: Write minimal implementation**

- В `SCRIPT` для `ips` добавить `index = $_.InterfaceIndex`.
- В `Adapter` — поле `listed: bool = True`.
- В `parse_snapshot` при обходе `ips` и `dns`: если адаптера с таким `alias`
  нет, создать `Adapter(alias, index=int(item.get("index") or 0), status="Up",
  description="", listed=False)`.
- `is_tunnel`: `if not adapter.listed: return True` перед проверкой описания —
  интерфейс, которого нет среди сетевых адаптеров, физическим быть не может.

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_netinfo.py tests/test_sys_windows_vpn.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/netinfo.py tests/test_sys_windows_netinfo.py
git commit -m "feat(sys): интерфейсы встроенных VPN в снимке сети Windows"
```

---

### Task 4.2: Встроенные VPN Windows (RAS)

**Files:**
- Create: `src/sys/windows/ras.py`
- Test: `tests/test_sys_windows_ras.py`

**Step 1: Write the failing tests**

```python
"""Встроенные VPN Windows: список, состояние, подключение."""

from __future__ import annotations

import json
import subprocess

from src.sys.windows import ras

LISTING = json.dumps(
    [
        {"name": "Office", "status": "Connected"},
        {"name": "Home", "status": "Disconnected"},
    ]
)


def test_parse_connections():
    assert ras.parse_connections(LISTING) == {"Office": True, "Home": False}


def test_single_object_and_garbage():
    assert ras.parse_connections(json.dumps({"name": "A", "status": "Connected"})) == {"A": True}
    assert ras.parse_connections("oops") == {}


def test_connect_uses_rasdial_exit_code(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ras.subprocess, "run", run)

    assert ras.connect("Office") is True
    assert seen == [["rasdial", "Office"]]


def test_disconnect(monkeypatch):
    seen = []
    monkeypatch.setattr(
        ras.subprocess, "run",
        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 691, "", ""),
    )

    assert ras.disconnect("Office") is False
    assert seen == [["rasdial", "Office", "/disconnect"]]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_ras.py -v --no-cov`
Expected: FAIL, `ImportError`

**Step 3: Write minimal implementation**

```python
"""Встроенные VPN Windows (IKEv2, L2TP, SSTP, PPTP).

Список и состояние — `Get-VpnConnection`: его поля не переводятся на язык
системы. Подключение — `rasdial` с сохранёнными учётными данными; вывод
`rasdial` переведён, поэтому значение имеет только код возврата.
"""

from __future__ import annotations

import json
import logging
import subprocess

from src.core.platform_info import no_window
from src.sys.windows.powershell import run_json

logger = logging.getLogger("tenga.sys.ras")

SCRIPT = (
    "@(@(Get-VpnConnection -ErrorAction SilentlyContinue) + "
    "@(Get-VpnConnection -AllUserConnection -ErrorAction SilentlyContinue) | "
    "ForEach-Object { @{ name = $_.Name; status = [string]$_.ConnectionStatus } }) "
    "| ConvertTo-Json -Compress"
)


def parse_connections(text: str) -> dict[str, bool]:
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return {}
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    return {
        str(item["name"]): item.get("status") == "Connected"
        for item in items
        if isinstance(item, dict) and item.get("name")
    }


def connections() -> dict[str, bool]:
    return parse_connections(run_json(SCRIPT))


def _rasdial(args: list[str]) -> bool:
    try:
        result = subprocess.run(
            ["rasdial", *args], capture_output=True, text=True, timeout=60, check=False,
            **no_window(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("rasdial failed: %s", e)
        return False
    if result.returncode != 0:
        logger.warning("rasdial %s returned %s", args[0], result.returncode)
    return result.returncode == 0


def connect(name: str) -> bool:
    return _rasdial([name])


def disconnect(name: str) -> bool:
    return _rasdial([name, "/disconnect"])
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_ras.py -v --no-cov`
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/sys/windows/ras.py tests/test_sys_windows_ras.py
git commit -m "feat(sys): встроенные VPN Windows через Get-VpnConnection и rasdial"
```

---

### Task 4.3: Туннели WireGuard через службу

**Files:**
- Create: `src/winsvc/wireguard.py`
- Modify: `src/winsvc/protocol.py` (`COMMANDS`: добавить `wireguard.list`)
- Modify: `src/winsvc/state.py` (методы `wireguard_list`, `wireguard_up`, `wireguard_down`)
- Modify: `src/winsvc/dispatch.py` (`ROUTES`)
- Test: `tests/test_winsvc_wireguard.py`

**Step 1: Write the failing tests**

```python
"""Туннели WireGuard: имена, команды wireguard.exe, состояние служб."""

from __future__ import annotations

import pytest

from src.winsvc import wireguard


def test_tunnel_names_from_configuration_dir(tmp_path):
    (tmp_path / "home.conf.dpapi").write_bytes(b"x")
    (tmp_path / "work-2.conf.dpapi").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")

    assert wireguard.list_tunnels(tmp_path) == ["home", "work-2"]


@pytest.mark.parametrize("bad", ["", "a" * 33, "x y", "..\\evil", "a;b"])
def test_bad_names_are_rejected(bad):
    with pytest.raises(ValueError):
        wireguard.validate_name(bad)


def test_up_command_points_at_dpapi_config(tmp_path):
    cmd = wireguard.up_command("home", exe="C:/WG/wireguard.exe", config_dir=tmp_path)

    assert cmd == ["C:/WG/wireguard.exe", "/installtunnelservice", str(tmp_path / "home.conf.dpapi")]


def test_down_command():
    assert wireguard.down_command("home", exe="wg.exe") == ["wg.exe", "/uninstalltunnelservice", "home"]


def test_service_name():
    assert wireguard.service_name("home") == "WireGuardTunnel$home"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_wireguard.py -v --no-cov`
Expected: FAIL, `ImportError`

**Step 3: Write minimal implementation**

`src/winsvc/wireguard.py`:

```python
"""Туннели WireGuard для Windows: что есть и как поднять.

Конфигурации лежат в каталоге данных WireGuard зашифрованными DPAPI и
доступны только SYSTEM, поэтому список и управление идут из службы. Служба
туннеля `WireGuardTunnel$<имя>` существует, пока туннель поднят.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Правило имён самого WireGuard для Windows.
_NAME = re.compile(r"[a-zA-Z0-9_=+.-]{1,32}")
SUFFIX = ".conf.dpapi"


def _program_files() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files"))


def default_exe() -> str:
    return str(_program_files() / "WireGuard" / "wireguard.exe")


def default_config_dir() -> Path:
    return _program_files() / "WireGuard" / "Data" / "Configurations"


def validate_name(name: str) -> str:
    if not _NAME.fullmatch(name or ""):
        raise ValueError(f"bad WireGuard tunnel name: {name!r}")
    return name


def service_name(name: str) -> str:
    return f"WireGuardTunnel${validate_name(name)}"


def list_tunnels(config_dir: Path | None = None) -> list[str]:
    directory = config_dir or default_config_dir()
    try:
        files = sorted(directory.iterdir())
    except OSError:
        return []
    names = [path.name[: -len(SUFFIX)] for path in files if path.name.endswith(SUFFIX)]
    return [name for name in names if _NAME.fullmatch(name)]


def up_command(name: str, *, exe: str | None = None, config_dir: Path | None = None) -> list[str]:
    config = (config_dir or default_config_dir()) / f"{validate_name(name)}{SUFFIX}"
    return [exe or default_exe(), "/installtunnelservice", str(config)]


def down_command(name: str, *, exe: str | None = None) -> list[str]:
    return [exe or default_exe(), "/uninstalltunnelservice", validate_name(name)]
```

`ServiceState`:

```python
    def wireguard_list(self) -> dict:
        return {"tunnels": wireguard.list_tunnels()}

    def wireguard_up(self, name: str) -> dict:
        try:
            command = wireguard.up_command(name)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        if name not in wireguard.list_tunnels():
            raise ServiceError(f"Туннель WireGuard «{name}» не найден")
        if not self._net.run(command):
            raise ServiceError(f"WireGuard не поднял туннель «{name}»")
        return {}

    def wireguard_down(self, name: str) -> dict:
        try:
            command = wireguard.down_command(name)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        if not self._net.run(command):
            raise ServiceError(f"WireGuard не опустил туннель «{name}»")
        return {}
```

`ROUTES` в `dispatch.py`:

```python
    "wireguard.list": ("wireguard_list", ()),
    "wireguard.up": ("wireguard_up", ("name",)),
    "wireguard.down": ("wireguard_down", ("name",)),
```

Тесты состояния (дописать в `tests/test_winsvc_state.py`): `wireguard_up` с
неизвестным именем → `ServiceError`; с известным (подменить
`wireguard.list_tunnels` через monkeypatch) → команда попала в
`FakeNet.commands`; имя с `;` → `ServiceError`, команда не выполнялась.

**Step 4: Run tests**

Run: `uv run pytest tests/test_winsvc_wireguard.py tests/test_winsvc_state.py tests/test_winsvc_dispatch.py tests/test_winsvc_protocol.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/winsvc tests/test_winsvc_wireguard.py tests/test_winsvc_state.py
git commit -m "feat(winsvc): подъём и опускание туннелей WireGuard"
```

---

### Task 4.4: `src/sys/windows/vpn.py` — настоящая реализация

**Files:**
- Modify: `src/sys/windows/vpn.py`
- Modify: `tests/test_sys_windows_vpn.py`

**Step 1: Write the failing tests**

```python
@pytest.fixture
def vpn_sources(monkeypatch):
    from src.sys.windows import ras, service_client

    state = {"ras": {"Office": True, "Home": False}, "wg_running": {"home": False}}

    class FakeClient:
        def __init__(self):
            self.calls = []

        def call(self, cmd, **args):
            self.calls.append((cmd, args))
            if cmd == "wireguard.list":
                return {"tunnels": ["home"]}
            return {}

    client = FakeClient()
    monkeypatch.setattr(ras, "connections", lambda: dict(state["ras"]))
    monkeypatch.setattr(ras, "connect", lambda name: state["ras"].__setitem__(name, True) or True)
    monkeypatch.setattr(ras, "disconnect", lambda name: True)
    monkeypatch.setattr(service_client, "get_client", lambda: client)
    monkeypatch.setattr(vpn, "_wireguard_running", lambda name: state["wg_running"].get(name, False))
    return state, client


def test_list_merges_ras_and_wireguard(vpn_sources):
    assert vpn.list_vpn_connections() == ["Home", "Office", "home"]


def test_ras_active(vpn_sources):
    assert vpn.is_vpn_active("Office") is True
    assert vpn.is_vpn_active("Home") is False


def test_ras_connect(vpn_sources):
    assert vpn.connect_vpn("Home") is True


def test_wireguard_connect_goes_to_service(vpn_sources):
    _state, client = vpn_sources

    assert vpn.connect_vpn("home") is True
    assert ("wireguard.up", {"name": "home"}) in client.calls


def test_unknown_connection_cannot_be_controlled(vpn_sources):
    assert vpn.connect_vpn("OpenVPN TAP") is False


def test_vpn_interface_is_the_connection_alias(vpn_sources, monkeypatch):
    data = dict(SNAPSHOT, ips=[*SNAPSHOT["ips"], {"alias": "Home", "ip": "10.9.0.2", "index": 55}])
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(data)))

    assert vpn.get_vpn_interface("Home") == "Home"
    assert vpn.get_vpn_interface("Nope") is None


def test_vpn_dns(vpn_sources):
    assert vpn.get_vpn_dns_servers("Office") == ["10.8.0.1"]
```

Удалить из файла тест `test_vpn_connect_is_not_available_yet`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_vpn.py -v --no-cov`
Expected: FAIL

**Step 3: Write minimal implementation**

Заменить VPN-функции в `src/sys/windows/vpn.py` (функции интерфейсов из фазы 1
оставить):

```python
from src.sys.windows import netinfo, ras, service_client
from src.winsvc.state import ServiceError


def _wireguard_tunnels() -> list[str]:
    try:
        return list(service_client.get_client().call("wireguard.list").get("tunnels", []))
    except ServiceError as e:
        logger.info("WireGuard tunnels are unavailable: %s", e)
        return []


def _wireguard_running(name: str) -> bool:
    from src.sys.windows.powershell import run_json
    from src.winsvc import wireguard

    try:
        service = wireguard.service_name(name)
    except ValueError:
        return False
    return run_json(f"(Get-Service -Name '{service}' -ErrorAction SilentlyContinue).Status").strip() == "Running"


def _wireguard_call(cmd: str, name: str) -> bool:
    try:
        service_client.get_client().call(cmd, name=name)
        return True
    except ServiceError as e:
        logger.warning("%s %s failed: %s", cmd, name, e)
        return False


def list_vpn_connections() -> list[str]:
    return sorted({*ras.connections(), *_wireguard_tunnels()})


def is_vpn_active(connection_name: str) -> bool:
    known = ras.connections()
    if connection_name in known:
        return known[connection_name]
    return _wireguard_running(connection_name)


def connect_vpn(connection_name: str) -> bool:
    if connection_name in ras.connections():
        return ras.connect(connection_name)
    if connection_name in _wireguard_tunnels():
        return _wireguard_call("wireguard.up", connection_name)
    logger.warning("VPN connection %s is not managed by Windows or WireGuard", connection_name)
    return False


def disconnect_vpn(connection_name: str) -> bool:
    if connection_name in ras.connections():
        return ras.disconnect(connection_name)
    if connection_name in _wireguard_tunnels():
        return _wireguard_call("wireguard.down", connection_name)
    return False


def get_vpn_interface(connection_name: str) -> str | None:
    # И у RAS, и у WireGuard имя интерфейса совпадает с именем подключения.
    netinfo.invalidate()
    adapter = netinfo.snapshot().adapter(connection_name)
    return adapter.alias if adapter else None


def get_vpn_dns_servers(connection_name: str) -> list[str]:
    adapter = netinfo.snapshot().adapter(connection_name)
    return list(adapter.dns) if adapter else []
```

`get_vpn_interface` сбрасывает кэш снимка: его вызывают сразу после
`connect_vpn`, и двухсекундный кэш показал бы состояние до подключения.
Проверить в `config_builder`/`connection`, нет ли там ожидания появления
интерфейса после подключения на Linux; если есть, повторить ту же логику.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/vpn.py tests/test_sys_windows_vpn.py
git commit -m "feat(sys): VPN-режимы на Windows: встроенные VPN и WireGuard"
```

---

### Task 4.5: Платформенные тексты интерфейса

**Files:**
- Create: `src/ui/logic/platform_texts.py`
- Modify: `src/ui/dialogs/profile_routing.py` (заголовок и описание группы VPN)
- Modify: `src/ui/dialogs/settings.py` (текст «AppImage для этой архитектуры отсутствует»)
- Modify: `gui.py` (подсказки об установке GTK — функция до маркера `# --- GTK bootstrap ---`)
- Test: `tests/test_ui_logic_platform_texts.py`, `tests/test_gui_entrypoint.py`

**Step 1: Write the failing tests**

```python
"""Тексты, которые зависят от ОС."""

from __future__ import annotations

from src.core import platform_info
from src.ui.logic import platform_texts


def test_linux_vpn_group(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert platform_texts.vpn_group_title() == "Подключение NetworkManager"


def test_windows_vpn_group(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "Windows" in platform_texts.vpn_group_title()
    assert "WireGuard" in platform_texts.vpn_group_description()


def test_missing_release_asset(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "установщик" in platform_texts.missing_release_asset()
```

В `tests/test_gui_entrypoint.py`:

```python
def test_install_hint_mentions_installer_on_windows(entry, monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "apt" not in entry.gtk_install_hint()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_logic_platform_texts.py tests/test_gui_entrypoint.py -v --no-cov`
Expected: FAIL

**Step 3: Write minimal implementation**

`src/ui/logic/platform_texts.py`:

```python
"""Тексты интерфейса, которые зависят от ОС (без GTK)."""

from __future__ import annotations

from src.core import platform_info


def vpn_group_title() -> str:
    return "VPN-подключение Windows" if platform_info.IS_WINDOWS else "Подключение NetworkManager"


def vpn_group_description() -> str:
    if platform_info.IS_WINDOWS:
        return (
            "Встроенный VPN Windows или туннель WireGuard, который профиль поднимает "
            "перед запуском прокси"
        )
    return "Профиль может поднимать VPN перед запуском прокси"


def missing_release_asset() -> str:
    if platform_info.IS_WINDOWS:
        return "установщик для этой системы отсутствует"
    return "AppImage для этой архитектуры отсутствует"
```

В диалогах заменить строковые литералы вызовами этих функций. В `gui.py` до
маркера:

```python
def gtk_install_hint() -> str:
    from src.core import platform_info

    if platform_info.IS_WINDOWS:
        return "Среда GTK входит в установщик: переустановите Tenga Proxy."
    return "Установите пакеты: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
```

и использовать её во всех местах `gui.py`, где печатается `sudo apt install …`.

**Step 4: Run tests**

Run: `uv run pytest -q` и `make test-gtk` (диалоги не сломались)
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/ui/logic/platform_texts.py src/ui/dialogs/profile_routing.py src/ui/dialogs/settings.py gui.py tests/test_ui_logic_platform_texts.py tests/test_gui_entrypoint.py
git commit -m "feat(ui): тексты про VPN, обновления и GTK зависят от ОС"
```

---

### Task 4.6: Уведомление об обновлении находит установщик

**Files:**
- Modify: `src/core/app_update.py` (`select_release`)
- Test: `tests/test_core_app_update.py`

**Step 1: Write the failing tests**

```python
def test_windows_release_needs_setup_exe(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy-0.18.0-windows-x64-setup.exe"}],
        }
    ]

    release = app_update.select_release(payload, "0.17.0", architecture="AMD64")

    assert release.has_asset is True


def test_windows_ignores_appimage(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy-0.18.0-x86_64.AppImage"}],
        }
    ]

    assert app_update.select_release(payload, "0.17.0", architecture="AMD64").has_asset is False
```

Посмотреть в существующих тестах `tests/test_core_app_update.py`, как
называются ассеты AppImage, и убедиться, что они не сломаются.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_core_app_update.py -v --no-cov`
Expected: FAIL — `has_asset` ищет `.appimage`

**Step 3: Write minimal implementation**

`platform.machine()` на Windows возвращает `AMD64`; `aliases` уже включают
`amd64` и `x86_64`, но имя установщика содержит `x64`. Добавить:

```python
from src.core import platform_info


def _asset_matches(name: str, aliases: tuple[str, ...]) -> bool:
    name = name.lower()
    if platform_info.IS_WINDOWS:
        return name.endswith("-setup.exe") and "windows" in name and (
            "x64" in name or any(alias in name for alias in aliases)
        )
    return name.endswith(".appimage") and any(alias in name for alias in aliases)
```

и заменить условие в `has_asset` на `_asset_matches(str(asset.get("name", "")), aliases)`.
Сохранить docstring модуля: «Executables are never installed here» — по-прежнему
верно, установщик только находится, пользователь открывает страницу релиза.

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_app_update.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/core/app_update.py tests/test_core_app_update.py
git commit -m "feat(core): уведомление об обновлении учитывает установщик Windows"
```

---

### Task 4.7: Публикация установщика в релиз

**Files:**
- Modify: `.github/workflows/windows.yml`

**Step 1: Триггер и шаг публикации**

```yaml
on:
  push:
    branches: [develop, master]
    tags: ["v*"]
  pull_request:
  workflow_dispatch:

permissions:
  contents: write
```

После загрузки артефакта:

```yaml
      - name: Attach installer to release
        if: startsWith(github.ref, 'refs/tags/v')
        shell: pwsh
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          $tag = "${{ github.ref_name }}"
          gh release view $tag 2>$null
          if ($LASTEXITCODE -ne 0) { gh release create $tag --draft --title $tag --notes "" }
          gh release upload $tag (Get-Item dist\windows\*.exe).FullName --clobber
```

Проверить: тег должен совпадать с `__version__` (`v0.18.0` ↔ `0.18.0`). Добавить
перед публикацией шаг, который сравнивает их и падает при расхождении.

**Step 2: Commit**

```bash
git add .github/workflows/windows.yml
git commit -m "ci: установщик Windows прикрепляется к релизу по тегу"
```

Сам тег создаёт владелец проекта при выпуске версии; исполнитель тег не
пушит.

---

### Task 4.8: Документация

**Files:**
- Modify: `README.md` (раздел «Установка»: подраздел Windows; «Что нужно в системе»)
- Modify: `docs/ru/installation.md`, `docs/en/installation.md`
- Modify: `docs/ru/vpn.md`, `docs/en/vpn.md` (встроенные VPN и WireGuard на Windows)
- Modify: `docs/ru/development.md`, `docs/en/development.md` (MSYS2, сборка, тесты `windows`, CI)
- Modify: `CLAUDE.md`

**Step 1: Содержание**

- **Установка на Windows:** скачать `tenga-proxy-<версия>-windows-x64-setup.exe`
  со страницы релизов, запустить (UAC), задачи мастера; где лежат настройки
  (`%APPDATA%\tenga-proxy`) и логи (`%LOCALAPPDATA%\tenga-proxy\logs`, служба —
  `%ProgramData%\tenga-proxy\logs`); как удалить.
- **TUN на Windows:** работает через службу «Tenga Proxy», которую ставит
  установщик; UAC при подключении не нужен; что служба делает и что
  откатывает. Ограничения: IPv6 не туннелируется (как и на Linux);
  локальный пользователь машины может управлять TUN через службу.
- **VPN на Windows:** встроенные подключения (имя как в «Параметры → Сеть →
  VPN», учётные данные должны быть сохранены), туннели WireGuard (имя как в
  WireGuard), OpenVPN и прочие — только использование уже поднятого адаптера.
  Совпадение имён — приоритет у встроенного VPN.
- **Ограничение установщика:** автозапуск и схемы ссылок пишутся в
  `HKCU` пользователя, от имени которого выполнена установка.
- **Разработка на Windows:** окружение MSYS2 из дорожной карты,
  `bash core/scripts/install_dev.sh`, `python gui.py`, `python -m pytest`,
  `bash core/scripts/build_windows.sh`; Windows-модули импортируются на Linux,
  маркер `windows`; интеграционный тест службы — только в CI или на VM.
- **CLAUDE.md:** в «Project Structure» — `src/sys/{linux,windows}/`,
  `src/winsvc/`, `src/ui/tray/win32/`, `packaging/windows/`, `svc_main.py`; в
  «Key Design Patterns» — абзац о фасадах `src/sys` и о
  `WindowsXrayManager`; в «Testing» — маркер `windows` и
  `tests/integration`; в «Building» — `build_windows.sh`, Inno Setup, CI;
  в «Single Instance» — mutex и pipe активации на Windows.

Тексты писать в стиле существующих документов (русский — основной, английский
— перевод). Скриншоты Windows — по возможности снять на VM при приёмке и
положить в `docs/screenshots/`.

**Step 2: Проверка сборки документации**

Run: `uv sync --extra docs && uv run mkdocs build --strict`
Expected: без предупреждений о битых ссылках

**Step 3: Commit**

```bash
git add README.md docs CLAUDE.md
git commit -m "docs: установка, TUN, VPN и разработка на Windows"
```

---

### Task 4.9: Итоговая приёмка на VM (владелец проекта)

Полный проход на чистой Windows 11 (и, если есть, Windows 10 22H2):

1. Установка с нуля из артефакта CI (или черновика релиза).
2. Сценарии приёмки фаз 1–3 повторно, кратко: прокси, трей, TUN, откат при
   сбоях, перезагрузка.
3. **Встроенный VPN:** создать IKEv2/L2TP-подключение в Windows с сохранённым
   паролем. Профиль с VPN «Office», режим `VPN_WITH_DIRECT_RULES`,
   «подключать автоматически»: при подключении профиля VPN поднимается, прямые
   правила идут через физический интерфейс, остальное — через VPN; при
   отключении профиля VPN опускается.
4. **WireGuard:** импортированный в WireGuard туннель, неактивный. Профиль с
   его именем и автоподключением: туннель поднимается и опускается вместе с
   профилем без запроса UAC.
5. Режим `VPN_WITH_PROXY_RULES` и `DIRECT_WITH_PROXY_RULES` с TUN: домены из
   правил идут через прокси, остальное — как задумано.
6. Уведомление об обновлении: поставить сборку с версией ниже последнего
   релиза — в настройках видно новую версию, кнопка открывает страницу релиза.
7. Обновление поверх установленной версии: служба перезапущена, настройки
   сохранились.
8. Удаление: служба удалена, сеть прямая, `%APPDATA%\tenga-proxy` на месте.

Результаты — в «Статус». После успешной приёмки — выпуск версии владельцем
(`python cli.py bump-version X.Y.Z`, тег `vX.Y.Z`).

---

## Статус

Код фазы выполнен (2026-10-23), задачи 4.1–4.8. Unit-тесты, lint,
`make test-gtk` и `mkdocs build --strict` зелёные; CI на `windows-latest`
зелёный. Задачи 4.0 (шаг 3, проверка `.conf.dpapi`) и 4.9 ждут VM владельца;
тег релиза создаёт владелец.

Отклонения от плана:

- **4.1.** Адаптер без записи в `Get-NetAdapter` создаётся только из
  `Get-NetIPAddress` (DNS добавляется к уже известному), и не для адресов
  `127.*`: иначе «Loopback Pseudo-Interface» попадал бы в список интерфейсов
  и считался туннелем.
- **4.2.** Скрипт `Get-VpnConnection` выводит UTF-8: имена подключений бывают
  кириллическими.
- **4.4.** `is_vpn_active` для имени вне RAS — служба туннеля WireGuard
  запущена *или* поднят адаптер с этим именем и IPv4: так профиль использует
  интерфейс OpenVPN и других клиентов, как сказано в «Принятых решениях».
  После `wireguard.up` `connect_vpn` до 5 секунд ждёт появления адаптера.
- **4.6.** `select_release` приводит архитектуру к нижнему регистру:
  `platform.machine()` на Windows — `AMD64`.
- **4.7.** Перед публикацией шаг сверяет тег с версией из `src/__init__.py`.

Если на шаге 3 задачи 4.0 `wireguard.exe /installtunnelservice` не примет
`.conf.dpapi`, `wireguard.up/down` нужно сузить до `sc start/stop` уже
установленной службы туннеля (см. задачу 4.0).
