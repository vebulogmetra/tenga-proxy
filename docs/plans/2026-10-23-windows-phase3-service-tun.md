# Фаза 3. Служба Windows и TUN-режим — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Контекст: `docs/plans/2026-10-23-windows-port-design.md` (разделы «Служба», «Протокол»,
> «Безопасность канала», «Маршруты», «DNS», «Откат»), дорожная карта `docs/plans/2026-10-23-windows-port-plan.md`.
> Предыдущая фаза: `docs/plans/2026-10-23-windows-phase2-delivery.md`.

**Goal:** TUN-режим на Windows: служба `TengaProxySvc` от SYSTEM запускает xray с wintun, ставит маршруты и DNS по командам GUI и при любом сбое возвращает сеть в исходное состояние.

**Architecture:** Пакет `src/winsvc/` делится на чистую логику (протокол, политика конфига, журнал отката, сборка команд `netsh`/PowerShell, состояние службы и диспетчер команд) и тонкий слой pywin32 (named pipe, ServiceFramework, установка). Чистая логика тестируется на Linux с подменёнными исполнителями. В GUI на Windows `AppContext.xray_manager` становится диспетчером: конфиг с inbound `tun` уходит в службу, остальные запускаются локально. Фасады `tun_route`/`tun_dns` на Windows вызывают соответствующие команды службы, поэтому `src/core/connection.py` не меняется.

**Tech Stack:** pywin32 (`win32pipe`, `win32file`, `win32service`, `win32serviceutil`, `servicemanager`, `win32security`), `netsh interface ipv4`, PowerShell `DnsClient` (NRPT), wintun 0.14.1, pytest.

---

## Принятые решения

Уточнения дизайна, найденные при планировании (дизайн-документ обновлён):

- **События — по опросу, без push.** Синхронный named pipe сериализует
  ввод-вывод на одном дескрипторе: блокирующее чтение в одном потоке держит
  запись в другом. Поэтому служба только отвечает на запросы. Строки лога
  xray и код его выхода приходят в ответе на `core.status`, который GUI и так
  опрашивает (монитор проверяет `is_running`). Буфер строк в службе ограничен
  1000 записями.
- **Служба запускается автоматически, с задержкой** (`delayed-auto`).
  Правила NRPT хранятся в реестре и переживают перезагрузку. При запуске по
  требованию после краша или перезагрузки посреди TUN-сессии DNS оставался бы
  сломанным, пока пользователь не откроет приложение. Автозапуск даёт откат по
  журналу при загрузке. Цена — простаивающий процесс (~25 МБ).
- **Интерфейсы в `netsh` задаются индексом**, а не именем: в именах бывают
  пробелы и скобки («Wi-Fi 2», «Ethernet (Kernel Debugger)»).
- **Маршруты — `store=active`**: исчезают при перезагрузке сами, журнал нужен
  для краша службы без перезагрузки.
- **Порядок записи журнала:** запись об откате делается *до* изменения, кроме
  правила NRPT, имя которого известно только после создания. На этот зазор есть
  страховка: при старте служба удаляет все правила NRPT с комментарием
  `tenga-proxy`.
- **Каталог службы** `%ProgramData%\tenga-proxy` получает при старте DACL:
  SYSTEM и администраторы — полный доступ, пользователи — только чтение (логи).
  Записи журнала при загрузке всё равно проверяются по схеме.
- **IPv6** туннелем не перехватывается — как и на Linux (там заменяется
  только IPv4 default). Это известное ограничение для обеих ОС, отдельная задача.
- **Один клиент за раз** (`nMaxInstances=1`): GUI — единственный экземпляр.

---

### Task 3.0: Сверка с кодом

**Step 1:** Фаза 2 выполнена: установщик собирается в CI, ручная приёмка
пройдена (раздел «Статус» фазы 2).

**Step 2:** Перечитать `src/core/connection.py` (порядок `xray_manager.start` →
`apply_tun_routes` → `route_system_dns_to_tun`; при отключении `stop` →
`restore_tun_routes`), `src/core/xray_manager.py` (`start`, `stop`,
`get_traffic`, `_core_logger`, `_pump_core_output`), `src/core/context.py`
(свойство `xray_manager`), `src/core/config_validator.py`
(`validate_session_config`, `exposed_inbounds`), `src/sys/windows/tun_route.py`
и `tun_dns.py` (заглушки фазы 1).

**Step 3:** Список методов `XrayManager`, которые вызываются снаружи:

```bash
grep -rhoE "xray_manager\.\w+" src | sort | uniq -c
```

На момент планирования: `start`, `stop`, `reload_config`, `is_running`,
`get_traffic`, `binary_path`. Если список шире, дополнить задачу 3.10.

**Step 4:** Результаты разведки (фаза 1, задача 1.0, пункты 4–5): имя адаптера
wintun и работает ли `sockopt.interface`. Если не работает — в задаче 3.5
привязку к интерфейсу на Windows не делать (вынести в «Статус»).

---

### Task 3.1: Общие константы и разрешение адреса (рефакторинг)

**Files:**
- Modify: `src/core/proxy_mode.py` (добавить `TUN_DNS_ADDRESS`)
- Modify: `src/sys/linux/tun_dns.py`, `src/sys/windows/tun_dns.py` (импорт константы)
- Modify: `src/sys/addresses.py` (перенести `resolve_ipv4`)
- Modify: `src/sys/linux/tun_route.py` (импорт `resolve_ipv4`; оставить `_resolve_ipv4 = resolve_ipv4` ради `tests/test_sys_tun_route.py`)

**Step 1:** Перенести `TUN_DNS_ADDRESS = "1.1.1.1"` вместе с комментарием в
`src/core/proxy_mode.py` рядом с `TUN_ADDRESS`. Linux- и Windows-модули
`tun_dns` импортируют её оттуда; фасад продолжает экспортировать имя.

**Step 2:** Перенести `_resolve_ipv4` из `src/sys/linux/tun_route.py` в
`src/sys/addresses.py` под именем `resolve_ipv4` (логгер — `tenga.sys.addresses`).

**Step 3:** Run: `uv run pytest -q` и `python cli.py lint-all` → зелёное.

**Step 4: Commit**

```bash
git add src/core/proxy_mode.py src/sys
git commit -m "refactor(sys): адрес DNS туннеля и разрешение хоста в общих модулях"
```

---

### Task 3.2: Протокол службы

**Files:**
- Create: `src/winsvc/__init__.py` (docstring: «Служба Windows: TUN, маршруты, DNS»)
- Create: `src/winsvc/protocol.py`
- Test: `tests/test_winsvc_protocol.py`

**Step 1: Write the failing tests**

```python
"""Сообщения канала GUI ↔ служба: JSON по строкам."""

from __future__ import annotations

import pytest

from src.winsvc.protocol import (
    MAX_LINE,
    LineReader,
    ProtocolError,
    Request,
    Response,
    decode_request,
    decode_response,
    encode,
)


def test_request_roundtrip():
    request = Request(id=3, cmd="core.status", args={})

    assert decode_request(encode(request)) == request


def test_response_roundtrip():
    response = Response(id=3, ok=False, error="нет адаптера")

    assert decode_response(encode(response)) == response


def test_encoded_message_is_one_line():
    data = encode(Request(id=1, cmd="core.start", args={"config": {"a": "x\ny"}}))

    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_unknown_command_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":1,"id":1,"cmd":"shell.exec","args":{}}\n')


def test_other_version_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":2,"id":1,"cmd":"hello","args":{}}\n')


def test_garbage_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b"not json\n")


def test_args_must_be_an_object():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":1,"id":1,"cmd":"hello","args":[]}\n')


def test_reader_splits_and_buffers_partial_lines():
    reader = LineReader()

    assert reader.feed(b'{"a":1}\n{"b"') == [b'{"a":1}']
    assert reader.feed(b":2}\n") == [b'{"b":2}']


def test_reader_refuses_oversized_line():
    reader = LineReader()

    with pytest.raises(ProtocolError):
        reader.feed(b"x" * (MAX_LINE + 1))
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_protocol.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/winsvc/protocol.py`:

```python
"""Канал GUI ↔ служба: одна JSON-строка на сообщение.

Запрос `{"v":1,"id":N,"cmd":"…","args":{…}}`, ответ
`{"v":1,"id":N,"ok":true,"result":{…}}` или `{"v":1,"id":N,"ok":false,"error":"…"}`.
Служба сама ничего не присылает: синхронный pipe не даёт читать и писать
одновременно, поэтому события (лог ядра, его выход) приходят в ответе на
`core.status`. Модуль не зависит от Windows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
# Конфиг сессии — десятки килобайт; мегабайты означают ошибку или атаку.
MAX_LINE = 4 * 1024 * 1024

COMMANDS = frozenset(
    {
        "hello",
        "core.start",
        "core.stop",
        "core.status",
        "core.stats",
        "routes.apply",
        "routes.restore",
        "dns.apply",
        "wireguard.up",
        "wireguard.down",
    }
)


class ProtocolError(ValueError):
    """Сообщение не соответствует протоколу."""


@dataclass(frozen=True)
class Request:
    id: int
    cmd: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    id: int
    ok: bool
    result: dict = field(default_factory=dict)
    error: str = ""


def encode(message: Request | Response) -> bytes:
    if isinstance(message, Request):
        payload = {"v": PROTOCOL_VERSION, "id": message.id, "cmd": message.cmd, "args": message.args}
    else:
        payload = {"v": PROTOCOL_VERSION, "id": message.id, "ok": message.ok}
        if message.ok:
            payload["result"] = message.result
        else:
            payload["error"] = message.error
    # ensure_ascii: перевод строки внутри значения экранируется, сообщение — одна строка.
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def _load(line: bytes) -> dict:
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"not JSON: {e}") from e
    if not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if not isinstance(data.get("id"), int):
        raise ProtocolError("missing id")
    return data


def decode_request(line: bytes) -> Request:
    data = _load(line)
    cmd = data.get("cmd")
    if cmd not in COMMANDS:
        raise ProtocolError(f"unknown command: {cmd!r}")
    args = data.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("args must be an object")
    return Request(id=data["id"], cmd=cmd, args=args)


def decode_response(line: bytes) -> Response:
    data = _load(line)
    ok = data.get("ok")
    if not isinstance(ok, bool):
        raise ProtocolError("missing ok")
    result = data.get("result", {})
    return Response(
        id=data["id"],
        ok=ok,
        result=result if isinstance(result, dict) else {},
        error=str(data.get("error", "")),
    )


class LineReader:
    """Режет поток байтов на строки, не давая буферу расти без предела."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b"\n")
        if len(self._buffer) > MAX_LINE or any(len(line) > MAX_LINE for line in lines):
            raise ProtocolError("line too long")
        return [line for line in lines if line.strip()]
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_winsvc_protocol.py -v --no-cov`
Expected: 9 passed

**Step 5: Commit**

```bash
git add src/winsvc/__init__.py src/winsvc/protocol.py tests/test_winsvc_protocol.py
git commit -m "feat(winsvc): протокол канала между GUI и службой"
```

---

### Task 3.3: Политика конфига службы

**Files:**
- Create: `src/winsvc/policy.py`
- Test: `tests/test_winsvc_policy.py`

**Step 1: Write the failing tests**

```python
"""Что служба от имени SYSTEM согласна запустить."""

from __future__ import annotations

import copy

import pytest

from src.winsvc.policy import PolicyError, sanitize_core_config

BASE = {
    "log": {"loglevel": "warning", "access": "C:/Windows/evil.txt", "error": "C:/x.log"},
    "inbounds": [
        {"tag": "tun-in", "protocol": "tun", "settings": {"name": "xray0"}},
        {"tag": "socks-in", "protocol": "mixed", "listen": "127.0.0.1", "port": 2080},
    ],
    "outbounds": [
        {
            "tag": "proxy",
            "protocol": "vless",
            "settings": {},
            "streamSettings": {"network": "ws", "wsSettings": {"path": "/ws"}},
        },
        {"tag": "direct", "protocol": "freedom"},
    ],
    "routing": {"rules": []},
}


def config(**changes):
    result = copy.deepcopy(BASE)
    result.update(changes)
    return result


def test_valid_config_passes_and_log_paths_are_dropped():
    result = sanitize_core_config(config())

    assert "access" not in result["log"]
    assert "error" not in result["log"]
    assert result["log"]["loglevel"] == "warning"


def test_transport_path_is_not_a_file():
    sanitize_core_config(config())


def test_inbound_on_all_interfaces_is_refused():
    bad = config()
    bad["inbounds"][1]["listen"] = "0.0.0.0"

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_unknown_inbound_protocol_is_refused():
    bad = config()
    bad["inbounds"].append({"tag": "x", "protocol": "vless", "listen": "127.0.0.1", "port": 1})

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_unix_socket_inbound_is_refused():
    bad = config()
    bad["inbounds"][1]["listen"] = "C:\\Windows\\Temp\\s.sock"

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


@pytest.mark.parametrize("key", ["certificateFile", "keyFile", "masterKeyLog"])
def test_file_keys_are_refused_anywhere(key):
    bad = config()
    bad["outbounds"][0]["streamSettings"]["tlsSettings"] = {"certificates": [{key: "C:/x"}]}

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_external_geo_file_outside_assets_is_refused():
    bad = config(routing={"rules": [{"domain": ["ext:..\\..\\secret.dat:x"], "outboundTag": "proxy"}]})

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_client_api_inbound_is_dropped():
    with_api = config()
    with_api["inbounds"].append({"tag": "api", "protocol": "dokodemo-door", "listen": "127.0.0.1"})

    result = sanitize_core_config(with_api)

    assert all(inbound.get("tag") != "api" for inbound in result["inbounds"])


def test_session_validator_violations_are_refused():
    bad = config(outbounds=[{"tag": "direct", "protocol": "freedom"}])

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_input_is_not_modified():
    original = config()
    snapshot = copy.deepcopy(original)

    sanitize_core_config(original)

    assert original == snapshot
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_policy.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/winsvc/policy.py`:

```python
"""Что служба соглашается запустить от имени SYSTEM.

Канал открыт интерактивным пользователям, поэтому конфиг от клиента считается
недоверенным. Запрещено всё, что дало бы через ядро доступ к файлам или
открыло бы порт наружу: пути к файлам, входы не на loopback, внешние геобазы
вне каталога ядра. Пути логов убираются — вывод ядра служба пишет в свой лог.
Остальные смысловые инварианты проверяет тот же `validate_session_config`, что
и GUI перед запуском.
"""

from __future__ import annotations

import copy
import ipaddress
from typing import Any

from src.core.config_validator import validate_session_config

ALLOWED_INBOUNDS = frozenset({"tun", "socks", "http", "mixed", "dokodemo-door"})
# Ключи, значение которых ядро открывает как файл на чтение или запись.
FILE_KEYS = frozenset({"certificateFile", "keyFile", "masterKeyLog"})
API_TAG = "api"


class PolicyError(ValueError):
    """Конфиг не может быть запущен службой."""


def _is_loopback(listen: str) -> bool:
    try:
        return ipaddress.ip_address(listen).is_loopback
    except ValueError:
        return listen == "localhost"


def _walk(node: Any, problems: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FILE_KEYS:
                problems.append(f"file reference is not allowed: {key}")
            _walk(value, problems)
    elif isinstance(node, list):
        for value in node:
            _walk(value, problems)
    elif isinstance(node, str) and node.startswith("ext:"):
        filename = node[4:].split(":", 1)[0]
        if "/" in filename or "\\" in filename or ".." in filename:
            problems.append(f"external geo file outside the core directory: {node}")


def sanitize_core_config(config: dict) -> dict:
    result = copy.deepcopy(config)
    problems: list[str] = []

    result["inbounds"] = [
        inbound for inbound in result.get("inbounds", []) if inbound.get("tag") != API_TAG
    ]
    for inbound in result["inbounds"]:
        protocol = inbound.get("protocol")
        if protocol not in ALLOWED_INBOUNDS:
            problems.append(f"inbound protocol is not allowed: {protocol}")
        if protocol != "tun" and not _is_loopback(str(inbound.get("listen", "127.0.0.1"))):
            problems.append(f"inbound must listen on loopback: {inbound.get('tag')}")

    log = result.get("log")
    if isinstance(log, dict):
        log.pop("access", None)
        log.pop("error", None)

    _walk(result, problems)
    problems.extend(validate_session_config(result))
    if problems:
        raise PolicyError("; ".join(problems))
    return result
```

Проверить: `validate_session_config` может требовать полей, которых нет в
`BASE` (например, правила для `dns-out`). Если тест
`test_valid_config_passes…` падает на нарушении валидатора, дополнить `BASE`
минимально нужным, а не ослаблять политику.

**Step 4: Run tests**

Run: `uv run pytest tests/test_winsvc_policy.py -v --no-cov`
Expected: всё зелёное

**Step 5: Сверка с настоящим конфигом**

Добавить тест: собрать TUN-конфиг тем же способом, что
`tests/test_core_tun_outbounds.py` (взять оттуда фикстуры контекста и профиля),
прогнать через `attach_health_inbound` и `sanitize_core_config` — политика не
должна отвергать то, что собирает сам GUI.

**Step 6: Commit**

```bash
git add src/winsvc/policy.py tests/test_winsvc_policy.py
git commit -m "feat(winsvc): политика конфига, который служба запускает от SYSTEM"
```

---

### Task 3.4: Журнал отката

**Files:**
- Create: `src/winsvc/journal.py`
- Test: `tests/test_winsvc_journal.py`

**Step 1: Write the failing tests**

```python
"""Журнал изменений сети: переживает краш службы."""

from __future__ import annotations

import json

from src.winsvc.journal import Journal

ROUTE = {"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40}
NRPT = {"op": "nrpt.remove", "name": "{6F1D2C3B-5A7E-4E0B-9C1D-2A3B4C5D6E7F}"}


def test_entries_survive_reopen(tmp_path):
    path = tmp_path / "svc-state.json"
    Journal(path).record(ROUTE)

    assert Journal(path).entries() == [ROUTE]


def test_rollback_runs_in_reverse_and_clears(tmp_path):
    journal = Journal(tmp_path / "j.json")
    journal.record(ROUTE)
    journal.record(NRPT)
    done = []

    journal.rollback(done.append)

    assert done == [NRPT, ROUTE]
    assert journal.entries() == []


def test_failed_undo_does_not_stop_the_rest(tmp_path):
    journal = Journal(tmp_path / "j.json")
    journal.record(ROUTE)
    journal.record(NRPT)
    done = []

    def undo(entry):
        if entry["op"] == "nrpt.remove":
            raise OSError("boom")
        done.append(entry)

    journal.rollback(undo)

    assert done == [ROUTE]
    assert journal.entries() == []


def test_malformed_entries_are_dropped_on_load(tmp_path):
    path = tmp_path / "j.json"
    path.write_text(
        json.dumps(
            [
                ROUTE,
                {"op": "shell", "cmd": "format c:"},
                {"op": "route.delete", "prefix": "x; rm", "index": 1},
                {"op": "nrpt.remove", "name": "not-a-guid"},
            ]
        )
    )

    assert Journal(path).entries() == [ROUTE]


def test_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / "j.json"
    path.write_text("{oops")

    assert Journal(path).entries() == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_journal.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/winsvc/journal.py`:

```python
"""Журнал отката: что служба изменила в сети и как это вернуть.

Запись делается до изменения (кроме NRPT, имя правила которого известно только
после создания), файл переписывается атомарно. Откат идёт в обратном порядке,
сбой одного шага не останавливает остальные. При загрузке записи проверяются
по схеме: файл лежит на диске, и доверять ему как коду нельзя.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("tenga.winsvc.journal")

_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")


def _valid(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    op = entry.get("op")
    if op == "route.delete":
        try:
            ipaddress.IPv4Network(str(entry.get("prefix")))
        except ValueError:
            return False
        return isinstance(entry.get("index"), int) and entry["index"] > 0
    if op == "nrpt.remove":
        return bool(_GUID.fullmatch(str(entry.get("name", ""))))
    return False


class Journal:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Journal is unreadable, starting empty: %s", e)
            return []
        entries = data if isinstance(data, list) else []
        valid = [entry for entry in entries if _valid(entry)]
        if len(valid) != len(entries):
            logger.warning("Dropped %d malformed journal entries", len(entries) - len(valid))
        return valid

    def _save(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries), encoding="utf-8")
        os.replace(tmp, self._path)

    def entries(self) -> list[dict]:
        with self._lock:
            return self._load()

    def record(self, entry: dict) -> None:
        if not _valid(entry):
            raise ValueError(f"invalid journal entry: {entry}")
        with self._lock:
            self._save([*self._load(), entry])

    def rollback(self, undo: Callable[[dict], None]) -> None:
        with self._lock:
            for entry in reversed(self._load()):
                try:
                    undo(entry)
                except Exception as e:
                    logger.warning("Undo failed for %s: %s", entry, e)
            self._save([])
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_winsvc_journal.py -v --no-cov`
Expected: 5 passed

**Step 5: Commit**

```bash
git add src/winsvc/journal.py tests/test_winsvc_journal.py
git commit -m "feat(winsvc): журнал отката изменений сети"
```

---

### Task 3.5: Команды изменения сети

**Files:**
- Create: `src/winsvc/netops.py`
- Test: `tests/test_winsvc_netops.py`

**Step 1: Write the failing tests**

```python
"""Команды netsh и PowerShell для маршрутов, DNS и NRPT."""

from __future__ import annotations

import pytest

from src.winsvc import netops


def test_route_add_on_link():
    assert netops.route_add("0.0.0.0/1", 40) == [
        "netsh", "interface", "ipv4", "add", "route",
        "prefix=0.0.0.0/1", "interface=40", "metric=1", "store=active",
    ]


def test_route_add_via_gateway():
    assert "nexthop=192.168.0.1" in netops.route_add("1.2.3.4/32", 12, "192.168.0.1")


def test_route_delete():
    assert netops.route_delete("0.0.0.0/1", 40) == [
        "netsh", "interface", "ipv4", "delete", "route",
        "prefix=0.0.0.0/1", "interface=40", "store=active",
    ]


def test_set_dns_uses_index():
    cmd = netops.set_dns(40, "1.1.1.1")

    assert "name=40" in cmd
    assert "address=1.1.1.1" in cmd


@pytest.mark.parametrize("bad", ["1.1.1.1; calc", "x", ""])
def test_addresses_are_validated(bad):
    with pytest.raises(ValueError):
        netops.set_dns(40, bad)


def test_index_must_be_positive_int():
    with pytest.raises(ValueError):
        netops.route_delete("0.0.0.0/1", 0)


def test_nrpt_add_script_mentions_comment_and_server():
    script = netops.nrpt_add_script("1.1.1.1")

    assert "Add-DnsClientNrptRule" in script
    assert "'1.1.1.1'" in script
    assert netops.NRPT_COMMENT in script


def test_nrpt_remove_requires_guid():
    with pytest.raises(ValueError):
        netops.nrpt_remove_script("'; Remove-Item C:\\ -Recurse; '")


def test_undo_maps_journal_entries_to_commands():
    calls = []
    net = netops.NetOps(run=lambda cmd: calls.append(cmd) or True, powershell=lambda s: "")

    net.undo({"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40})

    assert calls == [netops.route_delete("0.0.0.0/1", 40)]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_netops.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/winsvc/netops.py`:

```python
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
_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_NETSH_ROUTE = ["netsh", "interface", "ipv4"]


def _index(value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"bad interface index: {value!r}")
    return value


def _ipv4(value: str) -> str:
    return str(ipaddress.IPv4Address(value))


def _prefix(value: str) -> str:
    return str(ipaddress.IPv4Network(value))


def route_add(prefix: str, index: int, nexthop: str | None = None) -> list[str]:
    cmd = [*_NETSH_ROUTE, "add", "route", f"prefix={_prefix(prefix)}", f"interface={_index(index)}"]
    if nexthop:
        cmd.append(f"nexthop={_ipv4(nexthop)}")
    return [*cmd, "metric=1", "store=active"]


def route_delete(prefix: str, index: int) -> list[str]:
    return [
        *_NETSH_ROUTE, "delete", "route",
        f"prefix={_prefix(prefix)}", f"interface={_index(index)}", "store=active",
    ]


def set_dns(index: int, server: str) -> list[str]:
    return [
        *_NETSH_ROUTE, "set", "dnsservers", f"name={_index(index)}", "source=static",
        f"address={_ipv4(server)}", "register=none", "validate=no",
    ]


def set_metric(index: int, metric: int = 1) -> list[str]:
    return [*_NETSH_ROUTE, "set", "interface", f"interface={_index(index)}", f"metric={int(metric)}"]


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
```

Обратить внимание: `run_json` из фазы 1 возвращает stdout любой команды, не
только JSON, — имя историческое; использовать как есть.

**Step 4: Run tests**

Run: `uv run pytest tests/test_winsvc_netops.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/winsvc/netops.py tests/test_winsvc_netops.py
git commit -m "feat(winsvc): команды маршрутов, DNS и NRPT с проверкой аргументов"
```

---

### Task 3.6: Вывод ядра для подписчиков

Службе нужно пересылать строки xray в GUI, а GUI — писать пришедшие строки в
свой лог ядра. Сейчас логгер ядра закрыт внутри `XrayManager._core_logger`.

**Files:**
- Modify: `src/core/xray_manager.py`
- Test: `tests/test_core_xray_manager_log.py`

**Step 1: Write the failing test**

```python
def test_output_handler_receives_core_lines(tmp_path):
    import io
    import logging

    from src.core import xray_manager

    manager = xray_manager.XrayManager.__new__(xray_manager.XrayManager)
    manager._core_log = None
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    manager.add_output_handler(Collect())
    xray_manager._pump_core_output(io.BytesIO(b"first\nsecond\n"), manager._core_logger())

    assert lines == ["first", "second"]


def test_core_output_logger_is_shared_helper():
    from src.core import xray_manager

    assert xray_manager.core_output_logger() is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_core_xray_manager_log.py -v --no-cov`
Expected: FAIL, нет `add_output_handler`/`core_output_logger`

**Step 3: Write minimal implementation**

- Вынести тело `_core_logger` в функцию модуля `core_output_logger() -> logging.Logger`
  (тот же незарегистрированный логгер с `daily_file_handler(XRAY_LOG_FILE)`),
  `_core_logger` вызывает её и кэширует результат.
- Добавить метод:
  ```python
  def add_output_handler(self, handler: logging.Handler) -> None:
      """Ещё один получатель строк ядра (служба пересылает их в GUI)."""
      self._core_logger().addHandler(handler)
  ```

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_xray_manager_log.py tests/test_core_xray_manager.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/core/xray_manager.py tests/test_core_xray_manager_log.py
git commit -m "refactor(core): логгер вывода ядра доступен подписчикам"
```

---

### Task 3.7: Состояние службы и диспетчер команд

**Files:**
- Create: `src/winsvc/state.py`
- Create: `src/winsvc/dispatch.py`
- Test: `tests/test_winsvc_state.py`, `tests/test_winsvc_dispatch.py`

**Step 1: Write the failing tests for state**

```python
"""Состояние службы: ядро, маршруты, DNS, откат — с подменёнными системами."""

from __future__ import annotations

import json

import pytest

from src.core.xray_manager import TrafficStats
from src.sys.windows import netinfo
from src.winsvc.journal import Journal
from src.winsvc.state import ServiceError, ServiceState
from tests.test_sys_windows_netinfo import SNAPSHOT
from tests.test_winsvc_policy import BASE


class FakeRunner:
    def __init__(self):
        self.running = False
        self.started_with = None

    def start(self, config):
        self.started_with = config
        self.running = True
        return True, ""

    def stop(self):
        self.running = False
        return True, ""

    @property
    def is_running(self):
        return self.running

    def get_traffic(self):
        return TrafficStats(upload=5, download=7)


class FakeNet:
    def __init__(self):
        self.commands = []
        self.nrpt = []
        self.swept = False

    def run(self, cmd):
        self.commands.append(cmd)
        return True

    def nrpt_add(self, server):
        self.nrpt.append(server)
        return "{6F1D2C3B-5A7E-4E0B-9C1D-2A3B4C5D6E7F}"

    def nrpt_sweep(self):
        self.swept = True

    def undo(self, entry):
        self.commands.append(("undo", entry["op"]))

    def snapshot(self):
        return netinfo.parse_snapshot(json.dumps(SNAPSHOT))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def state(tmp_path):
    runner, net, clock = FakeRunner(), FakeNet(), Clock()
    service = ServiceState(
        runner=runner,
        net=net,
        journal=Journal(tmp_path / "j.json"),
        clock=clock,
        resolve=lambda host: "203.0.113.7",
        adapter_wait=0,
    )
    return service, runner, net, clock


def test_hello_reports_version_mismatch(state):
    service, *_ = state

    with pytest.raises(ServiceError):
        service.hello("0.0.1-other")


def test_core_start_sanitizes_config(state):
    service, runner, *_ = state

    service.core_start(BASE)

    assert "access" not in runner.started_with["log"]


def test_routes_apply_adds_host_route_then_split_default(state):
    service, _runner, net, _clock = state

    result = service.routes_apply("xray0", "vpn.example.com")

    added = [cmd for cmd in net.commands if "add" in cmd]
    assert "prefix=203.0.113.7/32" in added[0] and "nexthop=192.168.0.1" in added[0]
    assert {"prefix=0.0.0.0/1", "prefix=128.0.0.0/1"} <= {part for cmd in added for part in cmd}
    assert result == {"proxy_ip": "203.0.113.7"}


def test_routes_apply_without_tun_adapter_fails(state):
    service, *_ = state

    with pytest.raises(ServiceError):
        service.routes_apply("missing0", "vpn.example.com")


def test_loopback_proxy_gets_no_host_route(state):
    service, _runner, net, _clock = state
    service._resolve = lambda host: "127.0.0.1"

    service.routes_apply("xray0", "127.0.0.1")

    assert not any("prefix=127.0.0.1/32" in cmd for cmd in net.commands)


def test_dns_apply_records_nrpt_rule(state):
    service, _runner, net, _clock = state

    service.dns_apply("xray0")

    assert net.nrpt == ["1.1.1.1"]
    assert service._journal.entries()[-1]["op"] == "nrpt.remove"


def test_core_stop_rolls_everything_back(state):
    service, runner, net, _clock = state
    service.core_start(BASE)
    service.routes_apply("xray0", "vpn.example.com")
    service.dns_apply("xray0")

    service.core_stop()

    assert not runner.running
    assert service._journal.entries() == []
    assert ("undo", "nrpt.remove") in net.commands


def test_core_crash_is_noticed_by_tick(state):
    service, runner, _net, _clock = state
    service.core_start(BASE)
    service.routes_apply("xray0", "vpn.example.com")
    runner.running = False

    service.tick()

    assert service._journal.entries() == []
    status = service.core_status()
    assert status["running"] is False
    assert status["exited"] is True


def test_client_gone_stops_after_grace(state):
    service, runner, _net, clock = state
    service.core_start(BASE)
    service.client_gone()

    clock.now = 10
    service.tick()
    assert runner.running

    clock.now = 16
    service.tick()
    assert not runner.running


def test_reconnect_cancels_grace(state):
    service, runner, _net, clock = state
    service.core_start(BASE)
    service.client_gone()
    service.client_connected()

    clock.now = 100
    service.tick()

    assert runner.running


def test_startup_recovery_sweeps_nrpt_and_replays_journal(state):
    service, _runner, net, _clock = state
    service._journal.record({"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40})

    service.recover()

    assert net.swept
    assert ("undo", "route.delete") in net.commands


def test_log_lines_are_buffered_and_drained(state):
    service, *_ = state
    service.core_output("line 1")
    service.core_output("line 2")

    assert service.core_status()["log"] == ["line 1", "line 2"]
    assert service.core_status()["log"] == []


def test_stats(state):
    service, *_ = state

    assert service.core_stats() == {"upload": 5, "download": 7}
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_winsvc_state.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write `state.py`**

```python
"""Состояние службы: одно ядро, его маршруты и DNS, и как всё это вернуть.

Методы повторяют вызовы, которые `connection.py` делает на Linux, — фасады
`src/sys/windows` переадресуют их сюда. Каждое изменение сети сначала
записывается в журнал. Откат — при остановке ядра, его падении (замечает
`tick`), пропаже клиента дольше `GRACE_SECONDS` и при старте службы. Все
системные зависимости внедряются: в тестах — подделки.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections import deque

from src import __version__
from src.core.proxy_mode import TUN_DNS_ADDRESS
from src.sys.addresses import resolve_ipv4
from src.sys.windows import netinfo
from src.winsvc import netops
from src.winsvc.policy import PolicyError, sanitize_core_config

logger = logging.getLogger("tenga.winsvc.state")

GRACE_SECONDS = 15.0
LOG_BUFFER = 1000
SPLIT_DEFAULT = ("0.0.0.0/1", "128.0.0.0/1")


class ServiceError(RuntimeError):
    """Команду нельзя выполнить; текст уходит в GUI как есть."""


class ServiceState:
    def __init__(
        self,
        *,
        runner,
        net,
        journal,
        clock=time.monotonic,
        resolve=resolve_ipv4,
        adapter_wait: float = 5.0,
    ) -> None:
        self._runner = runner
        self._net = net
        self._journal = journal
        self._clock = clock
        self._resolve = resolve
        self._adapter_wait = adapter_wait
        self._lock = threading.RLock()
        self._log: deque[str] = deque(maxlen=LOG_BUFFER)
        self._expect_running = False
        self._exited = False
        self._gone_since: float | None = None

    # --- команды ---

    def hello(self, version: str) -> dict:
        if version != __version__:
            raise ServiceError(
                f"Версия службы {__version__} не совпадает с приложением {version}: "
                "переустановите Tenga Proxy"
            )
        return {"version": __version__}

    def core_start(self, config: dict) -> dict:
        try:
            sanitized = sanitize_core_config(config)
        except PolicyError as e:
            raise ServiceError(f"Конфигурация отклонена службой: {e}") from e
        with self._lock:
            self._stop_locked()
            ok, error = self._runner.start(sanitized)
            if not ok:
                raise ServiceError(error or "Не удалось запустить xray-core")
            self._expect_running = True
            self._exited = False
        return {}

    def core_stop(self) -> dict:
        with self._lock:
            self._stop_locked()
        return {}

    def core_status(self) -> dict:
        with self._lock:
            log = list(self._log)
            self._log.clear()
            return {"running": self._runner.is_running, "exited": self._exited, "log": log}

    def core_stats(self) -> dict:
        traffic = self._runner.get_traffic()
        return {"upload": traffic.upload, "download": traffic.download}

    def routes_apply(self, tun_name: str, proxy_host: str) -> dict:
        with self._lock:
            tun = self._wait_adapter(tun_name)
            route = netinfo.default_route(self._net.snapshot(), exclude=(tun_name,))
            if route is None:
                raise ServiceError("Не найден маршрут по умолчанию через физический интерфейс")
            proxy_ip = self._resolve(proxy_host)
            if not proxy_ip:
                raise ServiceError(f"Не удалось разрешить адрес прокси: {proxy_host}")

            if not ipaddress.IPv4Address(proxy_ip).is_loopback:
                self._add_route(f"{proxy_ip}/32", route.index, route.nexthop or None)
            for prefix in SPLIT_DEFAULT:
                self._add_route(prefix, tun.index, None)
            return {"proxy_ip": proxy_ip}

    def routes_restore(self) -> dict:
        with self._lock:
            self._rollback()
        return {}

    def dns_apply(self, tun_name: str) -> dict:
        with self._lock:
            tun = self._wait_adapter(tun_name)
            self._net.run(netops.set_dns(tun.index, TUN_DNS_ADDRESS))
            self._net.run(netops.set_metric(tun.index, 1))
            name = self._net.nrpt_add(TUN_DNS_ADDRESS)
            if name is None:
                raise ServiceError("Не удалось добавить правило NRPT")
            self._journal.record({"op": "nrpt.remove", "name": name})
        return {}

    # --- жизненный цикл ---

    def core_output(self, line: str) -> None:
        with self._lock:
            self._log.append(line)

    def client_connected(self) -> None:
        with self._lock:
            self._gone_since = None

    def client_gone(self) -> None:
        with self._lock:
            self._gone_since = self._clock()

    def tick(self) -> None:
        """Раз в секунду из потока службы: падение ядра и пропавший клиент."""
        with self._lock:
            if self._expect_running and not self._runner.is_running:
                logger.warning("xray-core exited unexpectedly, rolling back")
                self._expect_running = False
                self._exited = True
                self._rollback()
            if (
                self._gone_since is not None
                and self._expect_running
                and self._clock() - self._gone_since >= GRACE_SECONDS
            ):
                logger.info("Client is gone for %.0f s, stopping", GRACE_SECONDS)
                self._stop_locked()
                self._gone_since = None

    def recover(self) -> None:
        """При старте службы: убрать следы прошлой сессии."""
        with self._lock:
            self._net.nrpt_sweep()
            self._rollback()

    # --- внутреннее ---

    def _stop_locked(self) -> None:
        self._expect_running = False
        try:
            self._runner.stop()
        finally:
            self._rollback()

    def _rollback(self) -> None:
        self._journal.rollback(self._net.undo)
        netinfo.invalidate()

    def _add_route(self, prefix: str, index: int, nexthop: str | None) -> None:
        self._journal.record({"op": "route.delete", "prefix": prefix, "index": index})
        if not self._net.run(netops.route_add(prefix, index, nexthop)):
            raise ServiceError(f"Не удалось добавить маршрут {prefix}")

    def _wait_adapter(self, alias: str):
        deadline = self._clock() + self._adapter_wait
        while True:
            adapter = self._net.snapshot().adapter(alias)
            if adapter is not None:
                return adapter
            if self._clock() >= deadline:
                raise ServiceError(f"Адаптер {alias} не появился: ядро не создало TUN")
            netinfo.invalidate()
            time.sleep(0.25)
```

Настоящий `net` для службы — `NetOps` плюс метод `snapshot()`, делегирующий
`netinfo.snapshot()`. Добавить его в `NetOps` (задача 3.5) одной строкой:
`def snapshot(self): return netinfo.snapshot()`.

**Step 4: Write the failing tests for dispatch**

```python
"""Диспетчер: запрос → метод состояния → ответ, ошибки — в текст."""

from __future__ import annotations

from src.winsvc.dispatch import dispatch
from src.winsvc.protocol import Request
from src.winsvc.state import ServiceError


class FakeState:
    def core_status(self):
        return {"running": True}

    def routes_apply(self, tun_name, proxy_host):
        return {"proxy_ip": proxy_host}

    def core_stop(self):
        raise ServiceError("уже остановлено")

    def core_stats(self):
        raise RuntimeError("bug")


def test_call_with_args():
    response = dispatch(FakeState(), Request(1, "routes.apply", {"tun_name": "xray0", "proxy_host": "h"}))

    assert response.ok and response.result == {"proxy_ip": "h"}


def test_service_error_text_is_returned():
    response = dispatch(FakeState(), Request(2, "core.stop", {}))

    assert (response.ok, response.error) == (False, "уже остановлено")


def test_unexpected_error_is_hidden():
    response = dispatch(FakeState(), Request(3, "core.stats", {}))

    assert not response.ok
    assert "bug" not in response.error


def test_missing_args_are_an_error():
    response = dispatch(FakeState(), Request(4, "routes.apply", {"tun_name": "xray0"}))

    assert not response.ok
```

**Step 5: Write `dispatch.py`**

```python
"""Запрос протокола → метод `ServiceState` → ответ."""

from __future__ import annotations

import logging

from src.winsvc.protocol import Request, Response
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.winsvc.dispatch")

# Команда → (метод, обязательные аргументы).
ROUTES = {
    "hello": ("hello", ("version",)),
    "core.start": ("core_start", ("config",)),
    "core.stop": ("core_stop", ()),
    "core.status": ("core_status", ()),
    "core.stats": ("core_stats", ()),
    "routes.apply": ("routes_apply", ("tun_name", "proxy_host")),
    "routes.restore": ("routes_restore", ()),
    "dns.apply": ("dns_apply", ("tun_name",)),
}


def dispatch(state, request: Request) -> Response:
    route = ROUTES.get(request.cmd)
    if route is None:
        return Response(request.id, False, error=f"Команда не поддерживается: {request.cmd}")
    method, required = route
    missing = [name for name in required if name not in request.args]
    if missing:
        return Response(request.id, False, error=f"Нет аргументов: {', '.join(missing)}")
    try:
        result = getattr(state, method)(**{name: request.args[name] for name in required})
    except ServiceError as e:
        return Response(request.id, False, error=str(e))
    except Exception:
        logger.exception("Command %s failed", request.cmd)
        return Response(request.id, False, error="Внутренняя ошибка службы, подробности в её логе")
    return Response(request.id, True, result=result or {})
```

Команды `wireguard.*` есть в протоколе, но не в `ROUTES`: их добавляет фаза 4.

**Step 6: Run tests**

Run: `uv run pytest tests/test_winsvc_state.py tests/test_winsvc_dispatch.py -v --no-cov`
Expected: всё зелёное

**Step 7: Commit**

```bash
git add src/winsvc/state.py src/winsvc/dispatch.py src/winsvc/netops.py tests/test_winsvc_state.py tests/test_winsvc_dispatch.py
git commit -m "feat(winsvc): состояние службы, откат при сбоях и диспетчер команд"
```

---

### Task 3.8: Pipe-сервер, служба и её установка

Слой pywin32. На Linux проверяются только чистые части (`serve_connection`
поверх подменённого канала); остальное — тестами с маркером `windows` и
интеграционным тестом задачи 3.12.

**Files:**
- Create: `src/winsvc/server.py`
- Create: `src/winsvc/service.py`
- Create: `src/winsvc/install.py`
- Create: `svc_main.py` (точка входа exe службы, в корне рядом с `gui.py`)
- Test: `tests/test_winsvc_server.py`

**Step 1: Write the failing test**

```python
"""Обслуживание одного подключения поверх произвольного канала."""

from __future__ import annotations

from src.winsvc.protocol import Request, decode_response, encode
from src.winsvc.server import serve_connection


class FakeChannel:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = b""

    def read(self) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data: bytes) -> None:
        self.written += data


class FakeState:
    def __init__(self):
        self.events = []

    def client_connected(self):
        self.events.append("connected")

    def client_gone(self):
        self.events.append("gone")

    def core_status(self):
        return {"running": False}


def test_requests_are_answered_and_presence_tracked():
    data = encode(Request(1, "core.status", {}))
    channel = FakeChannel([data[:5], data[5:]])
    state = FakeState()

    serve_connection(channel, state)

    assert decode_response(channel.written.strip()).result == {"running": False}
    assert state.events == ["connected", "gone"]


def test_protocol_violation_closes_connection():
    channel = FakeChannel([b"garbage\n", encode(Request(2, "core.status", {}))])
    state = FakeState()

    serve_connection(channel, state)

    assert b'"ok":false' in channel.written
    assert state.events == ["connected", "gone"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_winsvc_server.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write `server.py`**

```python
"""Named pipe службы: один клиент за раз, запрос → ответ.

DACL канала: SYSTEM и администраторы — полный доступ, интерактивные
пользователи (IU) — чтение и запись. Удалённые клиенты отвергаются флагом
PIPE_REJECT_REMOTE_CLIENTS. `serve_connection` от Windows не зависит.
"""

from __future__ import annotations

import logging
import threading

from src.winsvc.dispatch import dispatch
from src.winsvc.protocol import LineReader, ProtocolError, Response, decode_request, encode

logger = logging.getLogger("tenga.winsvc.server")

PIPE_NAME = r"\\.\pipe\tenga-proxy-svc"
PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)"
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
BUFFER = 65536


def serve_connection(channel, state) -> None:
    """`channel.read()` → bytes (b"" — клиент ушёл), `channel.write(bytes)`."""
    state.client_connected()
    reader = LineReader()
    try:
        while True:
            data = channel.read()
            if not data:
                return
            for line in reader.feed(data):
                channel.write(encode(dispatch(state, decode_request(line))))
    except ProtocolError as e:
        logger.warning("Protocol violation, closing connection: %s", e)
        try:
            channel.write(encode(Response(0, False, error=f"Нарушение протокола: {e}")))
        except OSError:
            pass
    except OSError as e:
        logger.info("Client connection dropped: %s", e)
    finally:
        state.client_gone()


class _PipeChannel:
    def __init__(self, handle):
        self._handle = handle

    def read(self) -> bytes:
        import pywintypes
        import win32file

        try:
            _rc, data = win32file.ReadFile(self._handle, BUFFER)
            return bytes(data)
        except pywintypes.error:
            return b""

    def write(self, data: bytes) -> None:
        import pywintypes
        import win32file

        try:
            win32file.WriteFile(self._handle, data)
        except pywintypes.error as e:
            raise OSError(str(e)) from e


class PipeServer:
    def __init__(self, state) -> None:
        self._state = state
        self._stopping = threading.Event()

    def _create(self):
        import win32pipe
        import win32security

        attributes = win32security.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = (
            win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                PIPE_SDDL, win32security.SDDL_REVISION_1
            )
        )
        return win32pipe.CreateNamedPipe(
            PIPE_NAME,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT
            | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            BUFFER,
            BUFFER,
            0,
            attributes,
        )

    def serve_forever(self) -> None:
        import pywintypes
        import win32file
        import win32pipe

        while not self._stopping.is_set():
            handle = self._create()
            try:
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except pywintypes.error as e:
                    # ERROR_PIPE_CONNECTED: клиент успел подключиться раньше вызова.
                    if e.winerror != 535:
                        raise
                if self._stopping.is_set():
                    return
                serve_connection(_PipeChannel(handle), self._state)
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except pywintypes.error:
                    pass
                win32file.CloseHandle(handle)

    def stop(self) -> None:
        """Разбудить ConnectNamedPipe пустым подключением."""
        self._stopping.set()
        try:
            with open(PIPE_NAME, "r+b", buffering=0):
                pass
        except OSError:
            pass
```

**Step 4: Write `service.py`, `install.py`, `svc_main.py`**

`src/winsvc/service.py` — сборка зависимостей и ServiceFramework:

```python
"""Служба Windows TengaProxySvc: pipe-сервер, сторож ядра, откат при старте."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

SERVICE_NAME = "TengaProxySvc"
DISPLAY_NAME = "Tenga Proxy"
DESCRIPTION = "Запускает TUN-режим Tenga Proxy: xray-core, маршруты и DNS."
# Каталог службы: журнал, логи. Пользователям — только чтение.
DATA_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)"


def data_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "tenga-proxy"


def prepare_environment() -> None:
    """До импорта src.core.config: конфигурация и логи службы — в ProgramData."""
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["TENGA_CONFIG_DIR"] = str(directory)
    _restrict(directory)


def _restrict(directory: Path) -> None:
    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        DATA_SDDL, win32security.SDDL_REVISION_1
    )
    win32security.SetFileSecurity(
        str(directory), win32security.DACL_SECURITY_INFORMATION, descriptor
    )


def build_state():
    from src.core.xray_manager import XrayManager
    from src.winsvc.journal import Journal
    from src.winsvc.netops import NetOps
    from src.winsvc.state import ServiceState

    runner = XrayManager(binary_path=None)
    state = ServiceState(runner=runner, net=NetOps(), journal=Journal(data_dir() / "svc-state.json"))

    class _Forward(logging.Handler):
        def emit(self, record):
            state.core_output(record.getMessage())

    runner.add_output_handler(_Forward())
    return state


def run(stop_event: threading.Event) -> None:
    """Тело службы; вызывается из SvcDoRun и из `svc_main.py debug`."""
    from src.core.config import LOG_DIR
    from src.core.logging_utils import setup_logging
    from src.winsvc.server import PipeServer

    setup_logging(LOG_DIR / "tenga_service.log", level=logging.INFO)
    state = build_state()
    state.recover()
    server = PipeServer(state)
    thread = threading.Thread(target=server.serve_forever, name="pipe", daemon=True)
    thread.start()
    while not stop_event.wait(1.0):
        state.tick()
    server.stop()
    state.core_stop()


def framework_class():
    """Класс ServiceFramework; импорт pywin32 — только при запуске службы."""
    import servicemanager
    import win32service
    import win32serviceutil

    class TengaProxyService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self._stop = threading.Event()

        def SvcStop(self):  # noqa: N802 (имя задано pywin32)
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop.set()

        def SvcDoRun(self):  # noqa: N802
            servicemanager.LogInfoMsg(f"{SERVICE_NAME} started")
            run(self._stop)

    return TengaProxyService
```

Проверить, как называется функция настройки логов в
`src/core/logging_utils.py` и её сигнатуру; `setup_logging(file, level=…)`
используется в `gui.py`.

`src/winsvc/install.py`:

```python
"""Установка и удаление службы (вызывает установщик Inno Setup)."""

from __future__ import annotations

import subprocess
import sys

from src.core.platform_info import no_window
from src.winsvc.service import DESCRIPTION, DISPLAY_NAME, SERVICE_NAME

# Права на службу: SYSTEM и администраторы — полные, интерактивные
# пользователи (IU) — опрос, запуск (RP) и остановка (WP).
SERVICE_SDDL = (
    "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)"
    "(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
    "(A;;CCLCSWRPWPLOCRRC;;;IU)"
)


def install() -> None:
    import win32service

    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        handle = win32service.CreateService(
            scm,
            SERVICE_NAME,
            DISPLAY_NAME,
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_WIN32_OWN_PROCESS,
            win32service.SERVICE_AUTO_START,
            win32service.SERVICE_ERROR_NORMAL,
            f'"{sys.executable}"',
            None, 0, None, None, None,
        )
        try:
            win32service.ChangeServiceConfig2(
                handle, win32service.SERVICE_CONFIG_DESCRIPTION, DESCRIPTION
            )
            win32service.ChangeServiceConfig2(
                handle, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, True
            )
        finally:
            win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(scm)
    subprocess.run(["sc.exe", "sdset", SERVICE_NAME, SERVICE_SDDL], check=True, **no_window())
    subprocess.run(["sc.exe", "start", SERVICE_NAME], check=False, **no_window())


def remove() -> None:
    import win32serviceutil

    try:
        win32serviceutil.StopService(SERVICE_NAME)
    except Exception:
        pass
    win32serviceutil.RemoveService(SERVICE_NAME)


def cleanup() -> None:
    """Откат сети без службы: для удаления приложения, если служба сломана."""
    from src.winsvc.service import build_state, prepare_environment

    prepare_environment()
    build_state().recover()
```

`svc_main.py`:

```python
"""Точка входа tenga-proxy-svc.exe.

Без аргументов — запуск службой (диспетчер SCM). Аргументы: install, remove,
cleanup (для установщика) и debug (служба в консоли до Ctrl+C).
"""

import sys
import threading


def main() -> int:
    from src.winsvc import service

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in ("install", "remove", "cleanup"):
        from src.winsvc import install

        getattr(install, command)()
        return 0

    service.prepare_environment()
    if command == "debug":
        stop = threading.Event()
        try:
            service.run(stop)
        except KeyboardInterrupt:
            stop.set()
        return 0

    import servicemanager

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(service.framework_class())
    servicemanager.StartServiceCtrlDispatcher()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Важно: `prepare_environment()` вызывается до любого импорта `src.core.config`
(он вычисляет каталоги при импорте). `install`/`remove` конфиг не трогают.

**Step 5: Run tests**

Run: `uv run pytest tests/test_winsvc_server.py -v --no-cov` и `python cli.py lint-all`
Expected: зелёное

**Step 6: Commit**

```bash
git add src/winsvc/server.py src/winsvc/service.py src/winsvc/install.py svc_main.py tests/test_winsvc_server.py
git commit -m "feat(winsvc): named pipe, служба Windows и её установка"
```

---

### Task 3.9: Клиент службы в GUI

**Files:**
- Create: `src/sys/windows/service_client.py`
- Test: `tests/test_sys_windows_service_client.py`

**Step 1: Write the failing tests**

На Linux настоящий сервер заменяется потоком, который обслуживает
`socket.socketpair()` той же функцией `serve_connection`.

```python
"""Клиент канала службы поверх socketpair и настоящего serve_connection."""

from __future__ import annotations

import socket
import threading

import pytest

from src import __version__
from src.sys.windows.service_client import ServiceClient, ServiceUnavailable
from src.winsvc.server import serve_connection
from src.winsvc.state import ServiceError


class SocketChannel:
    def __init__(self, sock):
        self.sock = sock

    def read(self):
        return self.sock.recv(65536)

    def write(self, data):
        self.sock.sendall(data)

    def close(self):
        self.sock.close()


class FakeState:
    def client_connected(self):
        pass

    def client_gone(self):
        pass

    def hello(self, version):
        if version != __version__:
            raise ServiceError("версия")
        return {"version": version}

    def core_status(self):
        return {"running": True, "exited": False, "log": ["a"]}

    def core_stop(self):
        raise ServiceError("нечего останавливать")


@pytest.fixture
def client():
    server_sock, client_sock = socket.socketpair()
    thread = threading.Thread(
        target=serve_connection, args=(SocketChannel(server_sock), FakeState()), daemon=True
    )
    thread.start()
    result = ServiceClient(opener=lambda: SocketChannel(client_sock), starter=lambda: None)
    yield result
    result.close()


def test_call_returns_result(client):
    assert client.call("core.status")["log"] == ["a"]


def test_service_error_is_raised_with_text(client):
    with pytest.raises(ServiceError, match="нечего"):
        client.call("core.stop")


def test_unavailable_service_is_reported():
    def opener():
        raise OSError("pipe not found")

    broken = ServiceClient(opener=opener, starter=lambda: None, connect_timeout=0.2)

    with pytest.raises(ServiceUnavailable):
        broken.call("core.status")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_service_client.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""Клиент службы Tenga Proxy для GUI.

Подключение ленивое и одно на процесс: при первом вызове служба запускается
через SCM (если остановлена), затем `hello` сверяет версии. Обрыв канала
сбрасывает подключение, следующий вызов откроет его заново. Вызовы
сериализуются замком: канал синхронный, запрос → ответ.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time

from src import __version__
from src.winsvc.protocol import LineReader, Request, decode_response, encode
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.sys.service_client")

UNAVAILABLE = "Служба Tenga Proxy недоступна: переустановите приложение"


class ServiceUnavailable(ServiceError):
    pass


class _PipeFile:
    def __init__(self):
        from src.winsvc.server import PIPE_NAME

        self._file = open(PIPE_NAME, "r+b", buffering=0)  # noqa: SIM115

    def read(self) -> bytes:
        return self._file.read(65536)

    def write(self, data: bytes) -> None:
        self._file.write(data)

    def close(self) -> None:
        self._file.close()


def _start_service() -> None:
    import win32serviceutil

    from src.winsvc.service import SERVICE_NAME

    try:
        win32serviceutil.StartService(SERVICE_NAME)
    except Exception as e:
        # 1056: уже запущена — это нормально.
        if getattr(e, "winerror", None) != 1056:
            logger.debug("StartService: %s", e)


class ServiceClient:
    def __init__(self, *, opener=_PipeFile, starter=_start_service, connect_timeout: float = 10.0):
        self._opener = opener
        self._starter = starter
        self._connect_timeout = connect_timeout
        self._channel = None
        self._reader = LineReader()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def _connect(self) -> None:
        self._starter()
        deadline = time.monotonic() + self._connect_timeout
        while True:
            try:
                self._channel = self._opener()
                break
            except OSError as e:
                if time.monotonic() >= deadline:
                    raise ServiceUnavailable(UNAVAILABLE) from e
                time.sleep(0.2)
        self._reader = LineReader()
        self._exchange("hello", {"version": __version__})

    def _exchange(self, cmd: str, args: dict) -> dict:
        request = Request(next(self._ids), cmd, args)
        self._channel.write(encode(request))
        while True:
            data = self._channel.read()
            if not data:
                raise OSError("service closed the connection")
            lines = self._reader.feed(data)
            if lines:
                response = decode_response(lines[0])
                if not response.ok:
                    raise ServiceError(response.error)
                return response.result

    def call(self, cmd: str, **args) -> dict:
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._channel is None:
                        self._connect()
                    return self._exchange(cmd, args)
                except OSError as e:
                    self._drop()
                    if attempt == 2:
                        raise ServiceUnavailable(UNAVAILABLE) from e
        raise AssertionError("unreachable")

    def _drop(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except OSError:
                pass
        self._channel = None

    def close(self) -> None:
        with self._lock:
            self._drop()


_client: ServiceClient | None = None
_client_lock = threading.Lock()


def get_client() -> ServiceClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ServiceClient()
        return _client
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_service_client.py -v --no-cov`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/sys/windows/service_client.py tests/test_sys_windows_service_client.py
git commit -m "feat(sys): клиент службы Tenga Proxy в GUI"
```

---

### Task 3.10: Ядро в службе и диспетчер `xray_manager` на Windows

**Files:**
- Create: `src/sys/windows/core_runner.py`
- Modify: `src/core/proxy_mode.py` (`has_tun_inbound`)
- Modify: `src/core/context.py` (свойство `xray_manager`)
- Test: `tests/test_sys_windows_core_runner.py`, `tests/test_core_proxy_mode.py`

**Step 1: Write the failing tests**

```python
"""Ядро в службе и выбор между локальным и служебным запуском."""

from __future__ import annotations

from src.core.xray_manager import TrafficStats
from src.sys.windows.core_runner import ServiceCoreRunner, WindowsXrayManager
from src.winsvc.state import ServiceError

TUN = {"inbounds": [{"protocol": "tun"}]}
PROXY = {"inbounds": [{"protocol": "mixed"}]}


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, cmd, **args):
        self.calls.append(cmd)
        if self.fail == cmd:
            raise ServiceError("отказ службы")
        if cmd == "core.status":
            return {"running": True, "exited": False, "log": ["core says hi"]}
        if cmd == "core.stats":
            return {"upload": 1, "download": 2}
        return {}


class FakeLocal:
    binary_path = "C:/app/xray.exe"

    def __init__(self):
        self.running = False

    def start(self, config):
        self.running = True
        return True, ""

    def stop(self):
        self.running = False
        return True, ""

    @property
    def is_running(self):
        return self.running

    def get_traffic(self):
        return TrafficStats(9, 9)

    def get_version(self):
        return {"version": "26.9.9"}

    def set_on_stop_callback(self, callback):
        pass


def test_runner_reports_service_refusal():
    runner = ServiceCoreRunner(client=FakeClient(fail="core.start"), log_sink=lambda line: None)

    assert runner.start(TUN) == (False, "отказ службы")


def test_runner_status_forwards_log_lines():
    lines = []
    runner = ServiceCoreRunner(client=FakeClient(), log_sink=lines.append)

    assert runner.is_running is True
    assert lines == ["core says hi"]


def test_runner_traffic():
    runner = ServiceCoreRunner(client=FakeClient(), log_sink=lambda line: None)

    assert runner.get_traffic() == TrafficStats(1, 2)


def test_tun_config_goes_to_service():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=lambda l: None))

    assert manager.start(TUN) == (True, "")
    assert "core.start" in client.calls
    assert not local.running


def test_proxy_config_runs_locally():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=lambda l: None))

    manager.start(PROXY)

    assert local.running
    assert client.calls == []


def test_switching_mode_stops_previous_backend():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=lambda l: None))
    manager.start(PROXY)

    manager.start(TUN)

    assert not local.running


def test_stopped_manager_reports_nothing():
    manager = WindowsXrayManager(FakeLocal(), ServiceCoreRunner(client=FakeClient(), log_sink=print))

    assert manager.is_running is False
    assert manager.get_traffic() == TrafficStats()
```

В `tests/test_core_proxy_mode.py`:

```python
def test_has_tun_inbound():
    from src.core.proxy_mode import has_tun_inbound

    assert has_tun_inbound({"inbounds": [{"protocol": "tun"}]})
    assert not has_tun_inbound({"inbounds": [{"protocol": "mixed"}]})
    assert not has_tun_inbound({})
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_core_runner.py tests/test_core_proxy_mode.py -v --no-cov`
Expected: FAIL

**Step 3: Write minimal implementation**

`src/core/proxy_mode.py`:

```python
def has_tun_inbound(config: dict) -> bool:
    """Конфиг поднимает TUN-интерфейс: на Windows такой запускает служба."""
    return any(inbound.get("protocol") == "tun" for inbound in config.get("inbounds", []))
```

`src/sys/windows/core_runner.py`:

```python
"""xray-core на Windows: TUN — в службе, остальное — в процессе GUI.

`WindowsXrayManager` стоит на месте `XrayManager` в `AppContext` и выбирает,
кто запустит конфиг: TUN-интерфейс создать без прав администратора нельзя.
Снаружи он неотличим от `XrayManager` по тем методам, которыми пользуется
приложение (`start`, `stop`, `reload_config`, `is_running`, `get_traffic`,
`binary_path`).
"""

from __future__ import annotations

import logging

from src.core.proxy_mode import has_tun_inbound
from src.core.xray_manager import TrafficStats, core_output_logger
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.sys.core_runner")


class ServiceCoreRunner:
    def __init__(self, client=None, log_sink=None) -> None:
        if client is None:
            from src.sys.windows.service_client import get_client

            client = get_client()
        self._client = client
        self._log_sink = log_sink or core_output_logger().info
        self._on_stop = None

    def start(self, config: dict) -> tuple[bool, str]:
        try:
            self._client.call("core.start", config=config)
            return True, ""
        except ServiceError as e:
            return False, str(e)

    def stop(self) -> tuple[bool, str]:
        try:
            self._client.call("core.stop")
        except ServiceError as e:
            logger.warning("Service stop failed: %s", e)
        if self._on_stop:
            self._on_stop()
        return True, ""

    @property
    def is_running(self) -> bool:
        try:
            status = self._client.call("core.status")
        except ServiceError:
            return False
        for line in status.get("log", []):
            self._log_sink(line)
        return bool(status.get("running"))

    def get_traffic(self) -> TrafficStats:
        try:
            stats = self._client.call("core.stats")
        except ServiceError:
            return TrafficStats()
        return TrafficStats(int(stats.get("upload", 0)), int(stats.get("download", 0)))

    def set_on_stop_callback(self, callback) -> None:
        self._on_stop = callback


class WindowsXrayManager:
    def __init__(self, local, service: ServiceCoreRunner) -> None:
        self._local = local
        self._service = service
        self._active = None

    @property
    def binary_path(self) -> str:
        return self._local.binary_path

    def get_version(self):
        return self._local.get_version()

    def start(self, config: dict) -> tuple[bool, str]:
        self.stop()
        backend = self._service if has_tun_inbound(config) else self._local
        ok, error = backend.start(config)
        self._active = backend if ok else None
        return ok, error

    def stop(self) -> tuple[bool, str]:
        active, self._active = self._active, None
        if active is None:
            return True, ""
        return active.stop()

    def reload_config(self, config: dict) -> tuple[bool, str]:
        return self.start(config)

    @property
    def is_running(self) -> bool:
        return self._active is not None and self._active.is_running

    def get_traffic(self) -> TrafficStats:
        return self._active.get_traffic() if self._active is not None else TrafficStats()

    def set_on_stop_callback(self, callback) -> None:
        self._local.set_on_stop_callback(callback)
        self._service.set_on_stop_callback(callback)
```

`src/core/context.py`, свойство `xray_manager`: после создания
`XrayManager(binary_path=None)`:

```python
            from src.core import platform_info

            if platform_info.IS_WINDOWS:
                from src.sys.windows.core_runner import ServiceCoreRunner, WindowsXrayManager

                self._xray_manager = WindowsXrayManager(self._xray_manager, ServiceCoreRunner())
```

`ServiceCoreRunner()` клиента не подключает: подключение ленивое, служба
нужна только при первом TUN-запуске. Тип в аннотации свойства оставить
`XrayManager` (диспетчер совместим по используемым методам) — это не повод
вводить Protocol.

**Step 4: Run tests**

Run: `uv run pytest -q` и `python cli.py lint-all`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/core_runner.py src/core/proxy_mode.py src/core/context.py tests/test_sys_windows_core_runner.py tests/test_core_proxy_mode.py
git commit -m "feat(core): на Windows TUN-конфиг запускает служба, остальные — GUI"
```

---

### Task 3.11: Фасады `tun_route` и `tun_dns` на Windows через службу

**Files:**
- Modify: `src/sys/windows/tun_route.py`, `src/sys/windows/tun_dns.py`
- Modify: `tests/test_sys_windows_vpn.py` (тесты заглушек фазы 1 заменить)
- Test: `tests/test_sys_windows_tun.py`

**Step 1: Write the failing tests**

```python
"""Маршруты и DNS TUN на Windows — вызовы службы."""

from __future__ import annotations

import pytest

from src.sys.windows import service_client, tun_dns, tun_route
from src.winsvc.state import ServiceError


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, cmd, **args):
        self.calls.append((cmd, args))
        if cmd == self.fail:
            raise ServiceError("нет адаптера")
        return {"proxy_ip": "203.0.113.7"} if cmd == "routes.apply" else {}


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(service_client, "get_client", lambda: fake)
    return fake


def test_apply_returns_state(client):
    ok, state, error = tun_route.apply_tun_routes("xray0", "vpn.example.com")

    assert (ok, error) == (True, "")
    assert state == tun_route.TunRouteState(tun_name="xray0", proxy_ip="203.0.113.7")
    assert client.calls == [("routes.apply", {"tun_name": "xray0", "proxy_host": "vpn.example.com"})]


def test_apply_failure_text_reaches_ui(client):
    client.fail = "routes.apply"

    assert tun_route.apply_tun_routes("xray0", "h") == (False, None, "нет адаптера")


def test_restore_calls_service(client):
    assert tun_route.restore_tun_routes(tun_route.TunRouteState("xray0", "1.2.3.4")) == (True, "")
    assert client.calls[-1][0] == "routes.restore"


def test_restore_nothing_is_fine(client):
    assert tun_route.restore_tun_routes(None) == (True, "")
    assert client.calls == []


def test_dns(client):
    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert client.calls == [("dns.apply", {"tun_name": "xray0"})]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_tun.py -v --no-cov`
Expected: FAIL (заглушки возвращают отказ)

**Step 3: Write minimal implementation**

`src/sys/windows/tun_route.py`:

```python
"""Маршруты TUN на Windows: их ставит и снимает служба Tenga Proxy."""

from __future__ import annotations

from dataclasses import dataclass

from src.sys.windows import service_client
from src.winsvc.state import ServiceError


@dataclass
class TunRouteState:
    tun_name: str
    proxy_ip: str


def apply_tun_routes(tun_name: str, proxy_host: str) -> tuple[bool, TunRouteState | None, str]:
    try:
        result = service_client.get_client().call(
            "routes.apply", tun_name=tun_name, proxy_host=proxy_host
        )
    except ServiceError as e:
        return False, None, str(e)
    return True, TunRouteState(tun_name=tun_name, proxy_ip=result.get("proxy_ip", "")), ""


def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    if state is None:
        return True, ""
    try:
        service_client.get_client().call("routes.restore")
    except ServiceError as e:
        return False, str(e)
    return True, ""
```

`src/sys/windows/tun_dns.py` — по тому же образцу с командой `dns.apply`;
`TUN_DNS_ADDRESS` импортировать из `src.core.proxy_mode`.

Удалить из `tests/test_sys_windows_vpn.py` тесты заглушек
(`test_tun_routes_report_why_they_fail`, `test_restoring_nothing_is_fine`,
`test_tun_dns_reports_why_it_fails`) — их заменяет новый файл.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/tun_route.py src/sys/windows/tun_dns.py tests/test_sys_windows_tun.py tests/test_sys_windows_vpn.py
git commit -m "feat(sys): маршруты и DNS туннеля на Windows через службу"
```

---

### Task 3.12: Служба в сборке и установщике

**Files:**
- Modify: `packaging/windows/tenga-proxy.spec`
- Modify: `packaging/windows/tenga-proxy.iss`
- Modify: `core/scripts/build_windows.sh` (проверка второго exe)

**Step 1: Spec — второй exe с общим COLLECT**

```python
svc = Analysis(  # noqa: F821
    [str(ROOT / "svc_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    hiddenimports=["win32timezone", "servicemanager"],
    excludes=["tkinter", "gi"],
)
svc_pyz = PYZ(svc.pure)  # noqa: F821
svc_exe = EXE(  # noqa: F821
    svc_pyz,
    svc.scripts,
    [],
    exclude_binaries=True,
    name="tenga-proxy-svc",
    icon=str(ROOT / "assets" / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=True,
)

coll = COLLECT(  # noqa: F821
    gui_exe, gui.binaries, gui.datas,
    svc_exe, svc.binaries, svc.datas,
    name="tenga-proxy",
)
```

`excludes=["gi"]`: служба GTK не использует, а `src.core` не должен его
тянуть. Если анализ всё же находит `gi` через какой-то импорт `src.core`,
найти этот импорт и сделать его ленивым — служба не должна грузить GTK.

**Step 2: Inno Setup**

```iss
[Run]
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "install"; \
  StatusMsg: "Регистрация службы Tenga Proxy..."; Flags: runhidden waituntilterminated
; …прежний пункт запуска приложения

[UninstallRun]
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; \
  RunOnceId: "RemoveService"
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "cleanup"; Flags: runhidden waituntilterminated; \
  RunOnceId: "CleanupNetwork"

[Code]
// Обновление поверх установленной версии: служба держит exe, её нужно остановить
// до копирования файлов и зарегистрировать заново после.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop TengaProxySvc', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\sc.exe'), 'delete TengaProxySvc', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  Result := '';
end;
```

`remove` останавливает службу (она откатывает сеть в `SvcStop`), `cleanup` —
страховка на случай, если служба не ответила.

**Step 3: Build script**

В `build_windows.sh` после PyInstaller проверить наличие
`dist/windows/tenga-proxy/tenga-proxy-svc.exe`.

**Step 4: Commit**

```bash
git add packaging/windows core/scripts/build_windows.sh
git commit -m "build: служба Tenga Proxy в сборке и установщике"
```

---

### Task 3.13: Интеграционный тест службы в CI

**Files:**
- Create: `tests/integration/__init__.py`, `tests/integration/test_service_windows.py`
- Modify: `.github/workflows/windows.yml`
- Modify: `pyproject.toml` (`addopts`: исключить `tests/integration` из обычного прогона — `--ignore=tests/integration`)

**Риск:** маршруты `/1` в TUN на несколько секунд отрезают раннер от сети
(outbound теста никуда не ведёт). Агент раннера переживает короткие обрывы,
поэтому окно с поднятыми маршрутами держится минимальным: проверка и сразу
откат. Если job нестабилен, запускать тест только по `workflow_dispatch` и на
VM владельца; записать решение в «Статус».

**Step 1: Test**

```python
"""Служба на настоящей Windows: TUN, маршруты, NRPT и откат.

Запускается в CI после установки службы из собранного каталога:
    python -m pytest tests/integration -m windows
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from src.sys.windows.service_client import ServiceClient

pytestmark = pytest.mark.windows

# Outbound — SOCKS на закрытый порт loopback: трафик никуда не уходит, но
# валидатор сессии видит настоящий прокси-выход.
CONFIG = {
    "log": {"loglevel": "warning"},
    "inbounds": [
        {"tag": "tun-in", "protocol": "tun",
         "settings": {"name": "xray0", "MTU": 1500, "gateway": ["198.18.0.1/30"]}},
    ],
    "outbounds": [
        {"tag": "proxy", "protocol": "socks",
         "settings": {"servers": [{"address": "127.0.0.1", "port": 9}]}},
        {"tag": "direct", "protocol": "freedom"},
    ],
    "routing": {"rules": []},
}


def ps(script: str):
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script + " | ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return json.loads(out) if out else None


def routes_on(alias: str):
    data = ps(f"@(Get-NetRoute -InterfaceAlias '{alias}' -ErrorAction SilentlyContinue | "
              "Select-Object -ExpandProperty DestinationPrefix)")
    return set(data or [])


def nrpt_rules():
    data = ps("@(Get-DnsClientNrptRule | Where-Object Comment -eq 'tenga-proxy' | "
              "Select-Object -ExpandProperty Name)")
    return list(data or [])


@pytest.fixture
def client():
    result = ServiceClient()
    yield result
    try:
        result.call("core.stop")
    finally:
        result.close()


def test_tun_session_and_rollback(client):
    client.call("core.start", config=CONFIG)
    client.call("routes.apply", tun_name="xray0", proxy_host="127.0.0.1")
    client.call("dns.apply", tun_name="xray0")
    try:
        assert {"0.0.0.0/1", "128.0.0.0/1"} <= routes_on("xray0")
        assert len(nrpt_rules()) == 1
    finally:
        client.call("core.stop")

    assert not routes_on("xray0")
    assert nrpt_rules() == []


def test_core_crash_rolls_back(client):
    client.call("core.start", config=CONFIG)
    client.call("routes.apply", tun_name="xray0", proxy_host="127.0.0.1")
    subprocess.run(["taskkill", "/F", "/IM", "xray.exe"], check=False, capture_output=True)

    deadline = time.monotonic() + 5
    while routes_on("xray0") and time.monotonic() < deadline:
        time.sleep(0.5)

    assert not routes_on("xray0")
    assert client.call("core.status")["exited"] is True


def test_foreign_config_is_refused(client):
    bad = json.loads(json.dumps(CONFIG))
    bad["inbounds"].append({"tag": "open", "protocol": "socks", "listen": "0.0.0.0", "port": 1080})

    with pytest.raises(Exception, match="отклонена"):
        client.call("core.start", config=bad)
```

Внимание: `taskkill /IM xray.exe` убьёт и xray, запущенный тестами GUI, если
такой есть в том же прогоне; интеграционные тесты идут отдельным шагом.

**Step 2: CI**

В `.github/workflows/windows.yml` после сборки:

```yaml
      - name: Install service from build
        shell: pwsh
        run: |
          & dist\windows\tenga-proxy\tenga-proxy-svc.exe install
          Start-Sleep -Seconds 3
          Get-Service TengaProxySvc

      - name: Service integration tests
        run: |
          . .venv-win/bin/activate
          python -m pytest tests/integration -m windows -p no:cacheprovider --no-cov -v

      - name: Service log
        if: always()
        shell: pwsh
        run: Get-Content "$env:ProgramData\tenga-proxy\logs\*" -ErrorAction SilentlyContinue

      - name: Remove service
        if: always()
        shell: pwsh
        run: |
          & dist\windows\tenga-proxy\tenga-proxy-svc.exe remove
          & dist\windows\tenga-proxy\tenga-proxy-svc.exe cleanup
```

Версия службы и тестов совпадает: обе из того же `src/__init__.py`.

**Step 3: Проверить на GitHub**

Run: `git push`, `gh run watch`
Expected: job зелёный; при падении — лог службы в выводе шага «Service log».

**Step 4: Commit**

```bash
git add tests/integration .github/workflows/windows.yml pyproject.toml
git commit -m "ci: интеграционный тест службы и отката сети на Windows"
```

---

### Task 3.14: Ручная приёмка фазы 3 на VM (владелец проекта)

1. Установить сборку из CI поверх версии фазы 2. В «Службах» есть
   «Tenga Proxy», тип запуска «Автоматически (отложенный запуск)», состояние
   «Выполняется».
2. В приложении режим TUN, рабочий профиль, подключиться без запроса UAC.
   `Get-NetAdapter xray0` — адаптер есть. Сайты открываются, внешний IP — IP
   прокси.
3. Утечки DNS: https://dnsleaktest.com (расширенный тест) — только серверы со
   стороны прокси. `Get-DnsClientNrptRule` — одно правило `tenga-proxy`.
4. Отключиться: маршруты `0.0.0.0/1`, `128.0.0.0/1` и правило NRPT исчезли,
   сеть работает напрямую.
5. Подключиться и убить `tenga-proxy.exe` в Диспетчере задач: через ~15 с сеть
   вернулась к прямой.
6. Подключиться и убить `xray.exe`: через ~1 с сеть прямая, приложение
   показывает отключение (монитор видит `is_running = False`).
7. Подключиться и перезагрузить машину: после загрузки сеть и DNS работают,
   правил NRPT нет.
8. Переключение TUN → системный прокси → TUN без перезапуска приложения.
9. Лог службы `%ProgramData%\tenga-proxy\logs\` читается обычным
   пользователем, но не изменяется.
10. Удаление приложения во время TUN-сессии: сеть после удаления прямая,
    службы нет.

Результаты — в «Статус».

---

## Статус

Не начато.
