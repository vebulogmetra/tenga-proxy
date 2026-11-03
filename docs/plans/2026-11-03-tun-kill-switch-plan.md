# Блокировка трафика при обрыве (TUN, Linux, IPv6): план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** В режиме TUN на Linux трафик при обрыве не уходит напрямую: падение ядра обрабатывается, IPv6 закрыт всегда, а с настройкой «Блокировать трафик при обрыве» закрыт весь прямой трафик до отключения.

**Architecture:** Своя таблица `nftables` `inet veblock`, которую ставит и снимает root-помощник `tun-route-helper` по проверенным аргументам. Сокеты xray помечаются `sockopt.mark`, имя сервера xray разрешает сам (`sockopt.domainStrategy`). Жизненным циклом управляет `ConnectionService`, падение ядра ловит поток чтения вывода `XrayManager`, решение принимает `AppController` в главном потоке. Дизайн: `docs/plans/2026-11-03-tun-kill-switch-design.md`.

**Tech Stack:** Python 3.11, pytest, nftables 1.0.9, iproute2, systemd-resolved, NetworkManager (`nmcli`), POSIX sh для помощника, GTK 4/libadwaita и PySide6 для настроек.

**Правила для исполнителя:**
- На машине разработчика работает живой сеанс TUN (`xray0`). Не запускать xray с TUN-конфигом, не трогать `nft`, маршруты и `resolvectl` вне `sudo unshare -n` или виртуалки (см. память проекта и этап 2).
- Команды тестов: `uv run pytest <файл> -q -p no:cacheprovider --no-cov`. Линтер: `uv run python cli.py lint-all`.
- Тексты интерфейса на русском, комментарии в коде по стилю проекта (почему, а не что).
- Коммиты маленькие, сообщения в стиле репозитория: `fix(core): …`, `feat(sys): …`.

---

## Этап 1. Падение ядра

### Task 1.1: `XrayManager` сообщает о неожиданном выходе ядра

**Files:**
- Modify: `src/core/xray_manager.py:32-38` (`_pump_core_output`), `:110-115` (поля), `:169-171`, `:228-279` (`start`), `:317-348` (`stop`)
- Modify: `src/sys/windows/core_runner.py:64-65, 108-110`
- Test: `tests/test_core_xray_manager.py`

**Step 1: Написать падающие тесты**

В конец `tests/test_core_xray_manager.py`:

```python
import io
import threading


class _DeadProcess:
    """Процесс, который уже завершился: stdout пуст, poll отдаёт код."""

    pid = 4242

    def __init__(self) -> None:
        self.stdout = io.BytesIO(b"")
        self.returncode = 1

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return self.returncode


def _start_with(monkeypatch, manager, process, ready=True):
    monkeypatch.setattr("src.core.xray_manager.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr(manager, "_wait_for_process_ready", lambda timeout=2.0: ready)
    monkeypatch.setattr(manager, "_inject_stats_api", lambda config: config)
    return manager.start({"inbounds": [], "outbounds": []})


def test_unexpected_exit_is_reported_once_after_a_successful_start(monkeypatch):
    manager = _make_manager(monkeypatch)
    fired = threading.Event()
    manager.set_on_unexpected_exit(fired.set)

    ok, _ = _start_with(monkeypatch, manager, _DeadProcess())

    assert ok
    assert fired.wait(1.0)


def test_exit_during_startup_is_not_an_unexpected_exit(monkeypatch):
    """Ядро, упавшее в окне готовности — ошибка start(), а не обрыв."""
    manager = _make_manager(monkeypatch)
    fired = threading.Event()
    manager.set_on_unexpected_exit(fired.set)

    ok, _ = _start_with(monkeypatch, manager, _DeadProcess(), ready=False)

    assert not ok
    assert not fired.wait(0.2)


def test_requested_stop_is_not_an_unexpected_exit(monkeypatch):
    manager = _make_manager(monkeypatch)
    fired = threading.Event()
    manager.set_on_unexpected_exit(fired.set)

    class Living(_DeadProcess):
        """Живой процесс: stdout — настоящий pipe, EOF приходит только по terminate()."""

        def __init__(self):
            r, w = os.pipe()
            self.stdout, self._w = os.fdopen(r, "rb"), os.fdopen(w, "wb")
            self.returncode = None

        def terminate(self):
            self.returncode = 0
            self._w.close()

    process = Living()
    assert _start_with(monkeypatch, manager, process)[0]
    manager.stop()

    assert not fired.wait(0.2)
```

Добавить `import os` к импортам теста.

**Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/test_core_xray_manager.py -q -p no:cacheprovider --no-cov -k unexpected_exit`
Expected: FAIL, `AttributeError: 'XrayManager' object has no attribute 'set_on_unexpected_exit'`

**Step 3: Реализация**

В `src/core/xray_manager.py`:

```python
# поля в __init__, рядом с _on_stop_callback
self._on_unexpected_exit: Callable[[], None] | None = None
# Остановку запросили мы: конец вывода ядра — не обрыв.
self._stopping = False
# Ядро пережило окно готовности: конец вывода после этого — обрыв.
self._started = False


def set_on_unexpected_exit(self, callback: Callable[[], None] | None) -> None:
    """Колбэк на выход ядра, которого не просили. Зовётся из потока чтения вывода.

    Колбэк только сигналит: поток чтения не может ждать сам себя в
    `_cleanup`, а решение о перезапуске принимает главный поток.
    """
    self._on_unexpected_exit = callback


def _pump_and_report(self, stream, sink) -> None:
    _pump_core_output(stream, sink)
    if self._started and not self._stopping and self._on_unexpected_exit:
        try:
            self._on_unexpected_exit()
        except Exception:
            logger.exception("Error in unexpected-exit callback")
```

В `start()`: перед `Popen` — `self._stopping = False; self._started = False`; поток создаётся с `target=self._pump_and_report`; после успешного `_wait_for_process_ready` — `self._started = True`. Внимание на гонку: `_started` выставляется до `return True, ""`, а поток уже мог дочитать EOF; поэтому после `self._started = True` добавить проверку `if self._process.poll() is not None: self._cleanup(); return False, "xray-core exited …"` — ядро, умершее на границе, остаётся ошибкой старта.

В `stop()`: первой строкой после проверки `self._process is None` — `self._stopping = True`.

В `src/sys/windows/core_runner.py`: `ServiceCoreRunner.set_on_unexpected_exit` сохраняет колбэк (служба сама откатывает сеть, вызов колбэка — отдельная задача этапа Windows, оставить `self._on_unexpected_exit = callback`); `WindowsXrayManager.set_on_unexpected_exit` пробрасывает в оба, как `set_on_stop_callback`.

**Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_core_xray_manager.py tests/test_sys_windows_core_runner.py -q -p no:cacheprovider --no-cov`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/xray_manager.py src/sys/windows/core_runner.py tests/test_core_xray_manager.py
git commit -m "feat(core): сообщать о неожиданном выходе xray-core"
```

### Task 1.2: `ConnectionService.handle_core_exit()`

**Files:**
- Modify: `src/core/connection.py:240-272`
- Test: `tests/test_core_connection.py`

**Step 1: Написать падающие тесты**

```python
def test_core_exit_restores_routes_and_stops_the_monitor_but_keeps_vpn(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.config.proxy_mode = "tun"
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "tun"
    context.proxy_state.vpn_auto_connected = True
    context.monitor = MagicMock()
    restored = []
    monkeypatch.setattr("src.core.connection.restore_tun_routes", lambda s: restored.append(s) or (True, ""))
    disconnected = []
    monkeypatch.setattr("src.core.connection.disconnect_vpn", lambda name: disconnected.append(name) or True)
    service = ConnectionService(context)
    service._tun_route_state = "state"

    profile_id = service.handle_core_exit()

    assert profile_id == 1
    assert restored == ["state"]
    assert disconnected == []
    context.monitor.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()
    context.xray_manager.stop.assert_called_once()  # _cleanup: временный конфиг и сокет статистики


def test_core_exit_clears_the_system_proxy(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system_proxy"
    cleared = []
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: cleared.append(True))

    ConnectionService(context).handle_core_exit()

    assert cleared == [True]
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_connection.py -q -p no:cacheprovider --no-cov -k core_exit`
Expected: FAIL, `AttributeError: … has no attribute 'handle_core_exit'`

**Step 3: Реализация**

Вынести из `disconnect()` общую часть:

```python
def disconnect(self) -> ConnectionResult:
    """Stop xray-core and undo everything connect() has set up. …"""
    context = self._context
    try:
        stopped, error = context.xray_manager.stop()
        if not stopped:
            logger.error("Error stopping xray-core: %s", error)
    except Exception as e:
        logger.exception("Exception when stopping xray-core: %s", e)

    self._auto_disconnect_vpn()
    self._undo_runtime_mode()
    context.proxy_state.set_stopped()
    if context.monitor is not None:
        context.monitor.stop()
    return ConnectionResult(True)

def handle_core_exit(self) -> int:
    """Ядро вышло само: убрать маршруты и прокси, VPN оставить.

    VPN держится ради перезапуска: гасить и поднимать его заново —
    десятки секунд `nmcli`. Возвращает профиль упавшего сеанса.
    """
    context = self._context
    profile_id = getattr(context.proxy_state, "started_profile_id", -1)
    try:
        context.xray_manager.stop()  # процесс уже мёртв: это _cleanup
    except Exception:
        logger.debug("Cleanup after core exit failed", exc_info=True)
    self._undo_runtime_mode()
    context.proxy_state.set_stopped()
    if context.monitor is not None:
        context.monitor.stop()
    return profile_id

def _undo_runtime_mode(self) -> None:
    context = self._context
    started_mode = getattr(context.proxy_state, "started_mode", ProxyMode.TUN)
    if started_mode == ProxyMode.TUN:
        ok, error = restore_tun_routes(self._tun_route_state)
        if not ok:
            logger.warning("Failed to restore TUN routes: %s", error)
        self._tun_route_state = None
    if should_manage_system_proxy(started_mode):
        clear_system_proxy()
```

**Step 4: Прогнать**

Run: `uv run pytest tests/test_core_connection*.py -q -p no:cacheprovider --no-cov`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/connection.py tests/test_core_connection.py
git commit -m "feat(core): уборка после самостоятельного выхода ядра"
```

### Task 1.3: Контроллер перезапускает ядро один раз

**Files:**
- Modify: `src/ui/controller.py:410-428` (рядом с `watch_monitor`), `:381-391` (`_on_connection_done`)
- Modify: `src/ui/application.py:200, 322`, `src/ui/qt/application.py:501` (вызов `watch_core()` рядом с `watch_monitor()`)
- Test: `tests/test_ui_controller.py`

**Step 1: Падающие тесты** (по образцу существующих в `tests/test_ui_controller.py`: `ImmediateLoop`, подменная оболочка, `MagicMock` контекст — посмотреть фикстуры в начале файла и использовать их)

```python
CORE_EXIT_RESTART = "Ядро остановилось, переподключаюсь"
CORE_EXIT_GAVE_UP = "Ядро остановилось, трафик идёт напрямую"


def test_core_exit_reconnects_the_same_profile_once(controller, shell, monkeypatch):
    service = MagicMock()
    service.handle_core_exit.return_value = 1
    controller.set_connection_service(service)
    connected = []
    monkeypatch.setattr(controller, "connect_profile", lambda pid: connected.append(pid))
    now = [100.0]
    monkeypatch.setattr("src.ui.controller.time.monotonic", lambda: now[0])

    controller.watch_core()
    controller.context.xray_manager.set_on_unexpected_exit.assert_called_once()
    on_exit = controller.context.xray_manager.set_on_unexpected_exit.call_args[0][0]

    on_exit()
    assert connected == [1]
    assert any(CORE_EXIT_RESTART in t for t in shell.toasts)

    now[0] += 30
    on_exit()
    assert connected == [1]  # второго перезапуска за минуту нет
    assert any(CORE_EXIT_GAVE_UP in t for t in shell.toasts)
    assert shell.tray_states[-1][0] is ConnectionState.ERROR


def test_core_exit_while_connecting_is_deferred(controller, shell, monkeypatch):
    """Сигнал пришёл, пока поток подключения жив: обработать после него."""
    ...
```

Второй тест: `connection_busy()` возвращает `True` → `_on_core_exit` ставит флаг `_core_exit_pending`; `_on_connection_done` при флаге и `not xray_manager.is_running` вызывает `_on_core_exit` снова. Написать по образцу первого.

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_ui_controller.py -q -p no:cacheprovider --no-cov -k core_exit`
Expected: FAIL, `AttributeError: 'AppController' object has no attribute 'watch_core'`

**Step 3: Реализация**

```python
# в __init__
self._core_exit_at: float = 0.0
self._core_exit_pending = False

# --- падение ядра ---

CORE_RESTART_COOLDOWN = 60.0  # на уровне модуля

def watch_core(self) -> None:
    """Подписаться на самостоятельный выход ядра. Сигнал приходит из потока ядра."""
    self.context.xray_manager.set_on_unexpected_exit(
        lambda: self._loop.dispatch(self._on_core_exit)
    )

def _on_core_exit(self) -> None:
    if self.connection_busy():
        # Поток подключения ещё работает: разберёмся, когда он закончит.
        self._core_exit_pending = True
        return
    self._core_exit_pending = False
    service = self._ensure_connection_service()
    profile_id = service.handle_core_exit()
    self._refresh_window()
    if profile_id < 0:
        return
    now = time.monotonic()
    if now - self._core_exit_at < CORE_RESTART_COOLDOWN:
        self.notify_user(CORE_EXIT_GAVE_UP)
        self._shell.show_error(CORE_EXIT_GAVE_UP)
        self._shell.set_tray_state(ConnectionState.ERROR, "")
        return
    self._core_exit_at = now
    self.notify_user(CORE_EXIT_RESTART)
    self.connect_profile(profile_id)
```

В `_on_connection_done` в самом конце: `if self._core_exit_pending and not self.context.xray_manager.is_running: self._on_core_exit()`. Константы текстов — в `src/ui/controller.py` рядом с другими (`CONFIRM_DELETE` и т. п.). Добавить `import time`. В GTK и Qt приложениях вызвать `watch_core()` там же, где `watch_monitor()`.

**Step 4: Прогнать**

Run: `uv run pytest tests/test_ui_controller.py tests/test_ui_application.py -q -p no:cacheprovider --no-cov` (второй файл помечен `gtk` и пропустится без дисплея; затем `make test-gtk` и `make test-qt`)
Expected: PASS

**Step 5: Commit**

```bash
git add src/ui/controller.py src/ui/application.py src/ui/qt/application.py tests/test_ui_controller.py
git commit -m "feat(ui): перезапускать ядро после его падения"
```

### Task 1.4: Осиротевшее ядро при старте

**Files:**
- Create: `src/core/core_pid.py`
- Modify: `src/core/connection.py` (после успешного `start`), `gui.py:85-99` (`recover_network`)
- Test: `tests/test_core_core_pid.py`

**Step 1: Тесты**

```python
"""Осиротевшее ядро: приложение упало, xray остался с TUN и маршрутами."""

from __future__ import annotations

from src.core import core_pid


class FakeProc:
    def __init__(self, exe, terminated):
        self._exe, self._terminated = exe, terminated

    def exe(self):
        return self._exe

    def terminate(self):
        self._terminated.append("terminate")

    def wait(self, timeout=None):
        return 0


def test_orphan_with_our_binary_is_terminated(tmp_path, monkeypatch):
    pidfile = tmp_path / "xray.pid"
    monkeypatch.setattr(core_pid, "PID_FILE", pidfile)
    core_pid.remember(4242, "/usr/lib/tenga-proxy/core/bin/xray")
    calls = []
    monkeypatch.setattr(core_pid, "_process", lambda pid: FakeProc("/usr/lib/tenga-proxy/core/bin/xray", calls))

    assert core_pid.kill_orphan() is True
    assert calls == ["terminate"]
    assert not pidfile.exists()


def test_reused_pid_of_another_program_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(core_pid, "PID_FILE", tmp_path / "xray.pid")
    core_pid.remember(4242, "/usr/lib/tenga-proxy/core/bin/xray")
    calls = []
    monkeypatch.setattr(core_pid, "_process", lambda pid: FakeProc("/usr/bin/firefox", calls))

    assert core_pid.kill_orphan() is False
    assert calls == []


def test_missing_pidfile_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(core_pid, "PID_FILE", tmp_path / "xray.pid")
    assert core_pid.kill_orphan() is False
```

**Step 2:** Run: `uv run pytest tests/test_core_core_pid.py -q -p no:cacheprovider --no-cov` → FAIL `ModuleNotFoundError`

**Step 3: Реализация**

```python
"""Pid работающего ядра — на случай падения приложения.

xray запускается без PDEATHSIG: после SIGKILL приложения он живёт дальше с
TUN-интерфейсом и маршрутами. При следующем старте его нужно погасить до
возврата маршрутов, иначе `recover_tun_routes` вернёт маршрут под живым ядром.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import psutil

from src.core.config import CORE_DIR

logger = logging.getLogger("tenga.core.core_pid")
PID_FILE: Path = CORE_DIR / "xray.pid"


def remember(pid: int, binary: str) -> None:
    try:
        PID_FILE.write_text(json.dumps({"pid": pid, "binary": os.path.realpath(binary)}))
    except OSError:
        logger.debug("Cannot write pid file", exc_info=True)


def forget() -> None:
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def _process(pid: int):
    return psutil.Process(pid)


def kill_orphan() -> bool:
    """Погасить ядро прошлого сеанса, если pid всё ещё наш бинарник."""
    try:
        data = json.loads(PID_FILE.read_text())
        pid, binary = int(data["pid"]), str(data["binary"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        proc = _process(pid)
        if os.path.realpath(proc.exe()) != binary:
            forget()
            return False
        logger.warning("Orphaned xray-core %s from a crashed session, terminating", pid)
        proc.terminate()
        proc.wait(timeout=5)
    except (psutil.Error, OSError):
        forget()
        return False
    forget()
    return True
```

В `ConnectionService.connect()` после успешного `start`: `core_pid.remember(context.xray_manager.pid, context.xray_manager.binary_path)` — добавить `XrayManager.pid` (property, `self._process.pid`), в `WindowsXrayManager` вернуть `-1`, тогда `remember` пропускать при `pid < 0`. В `disconnect()`/`handle_core_exit()` — `core_pid.forget()`. В `gui.py::recover_network()` первой строкой `from src.core.core_pid import kill_orphan` и вызов `kill_orphan()` до `recover_tun_routes()`.

**Step 4:** Run: `uv run pytest tests/test_core_core_pid.py tests/test_core_connection*.py -q -p no:cacheprovider --no-cov` → PASS

**Step 5: Commit**

```bash
git add src/core/core_pid.py src/core/connection.py src/core/xray_manager.py src/sys/windows/core_runner.py gui.py tests/test_core_core_pid.py
git commit -m "fix(core): гасить осиротевшее ядро при старте"
```

### Task 1.5: Удалить `reload_config` и поправить комментарий о маршруте

**Files:**
- Modify: `src/core/connection.py:321-369`, `src/core/xray_manager.py:298-315`, `src/sys/windows/core_runner.py` (метод `reload_config`)
- Modify: `tests/test_core_connection.py`, `tests/test_core_connection_dns.py`, `tests/test_core_connection_validation.py`, `tests/test_core_config.py`, `tests/test_ui_application.py` — удалить тесты `reload`
- Modify: `src/sys/linux/tun_route.py:20-23`

**Step 1:** `grep -rn "reload_config" src tests cli.py` — убедиться, что вызывающих в `src/` и `cli.py` нет (только определения). Если `tests/test_ui_application.py` проверяет, что `apply_settings` *не* перезагружает ядро, — оставить этот тест, убрав упоминание метода.

**Step 2:** Удалить методы и их тесты. Комментарий в `tun_route.py` заменить:

```python
# Маршрут по умолчанию, который нужно вернуть. Переживает падение приложения:
# ядро умирает вместе с TUN, маршрут через него исчезает. Если у исходного
# маршрута была метрика, `ip route replace default dev xray0` его не заменял,
# а добавлял второй с метрикой 0 — тогда система продолжит ходить по исходному
# (это утечка, её закрывает tun_firewall). Если метрики не было, маршрут по
# умолчанию пропадает вовсе, пока его не вернёт `recover_tun_routes()`.
```

**Step 3:** Run: `uv run pytest -q -p no:cacheprovider --no-cov && uv run python cli.py lint-all` → PASS

**Step 4: Commit**

```bash
git commit -am "refactor(core): убрать неиспользуемый reload_config, уточнить комментарий о маршруте"
```

---

## Этап 2. Эксперименты (без кода в репозитории)

Выполнять в виртуалке с Ubuntu 24.04 и установленным deb (или с `setcap cap_net_admin,cap_net_raw+ep` на `core/bin/xray`). Результаты записать в раздел «Что проверить в первую очередь» дизайна как «проверено: …», а при провале — вернуться к выбору механизма.

### Task 2.1: Метка доходит до nftables на всех outbound

1. Конфиг `/tmp/mark.json`: inbound `socks` на `127.0.0.1:1081`; outbounds `freedom` tag `direct` с `"streamSettings": {"sockopt": {"mark": 32362, "interface": "<физический интерфейс>"}}`; `dns` с серверами `["1.1.1.1", "https+local://dns.google/dns-query"]`; `routing.domainStrategy: "IPOnDemand"`.
2. `sudo nft -f -` с таблицей: `table inet exp { chain out { type filter hook output priority 0; policy accept; oif lo accept; meta mark 0x7e6a counter accept; ip daddr 10.0.0.0/8 accept; counter reject with icmpx type admin-prohibited; } }`.
3. `xray run -c /tmp/mark.json &`, затем `curl -x socks5h://127.0.0.1:1081 https://example.com -o /dev/null -w '%{http_code}\n'`.
4. `sudo nft list table inet exp`: счётчик у `mark` растёт, у `reject` — ноль. Ожидание: `200`, запросы DNS внутреннего резолвера тоже помечены. Отдельно: с `https+local://` в `dns.servers` проверить, идёт ли DoH с меткой (по дизайну ожидается, что нет — тогда в TUN такой DNS держится только на `oifname xray0`).
5. `sudo nft delete table inet exp`.

### Task 2.2: `sockopt.domainStrategy` на proxy-outbound

1. Взять настоящий профиль с доменным адресом сервера и TLS/Reality. Собрать конфиг через `python cli.py` (посмотреть `cli.py --help`, команда вывода конфига) с SOCKS-inbound, добавить на proxy-outbound `"sockopt": {"mark": 32362, "domainStrategy": "UseIPv4"}`.
2. Таблица из 2.1 плюс строка `meta l4proto {tcp, udp} th dport 53 counter reject` перед `ip daddr 10.0.0.0/8 accept`.
3. Подключиться через SOCKS, проверить `curl` и счётчики: DNS-запрос к серверу шёл с меткой, `reject`-счётчики нулевые.
4. Проверить SNI: `sudo tcpdump -i <iface> -A 'tcp port 443' | grep -a <домен>` — в ClientHello домен сервера, не IP. Для Reality — в логе xray `debug` нет ошибок рукопожатия.
5. Без `domainStrategy` повторить: ожидание — `dport 53 reject` срабатывает, подключения нет. Это подтверждает необходимость настройки.

### Task 2.3: xray не создаёт своих таблиц

На машине разработчика при живом сеансе: `sudo nft list ruleset | head` — таблиц от xray быть не должно. Только чтение.

### Task 2.4: Записать результаты

Обновить дизайн (раздел «Что проверить в первую очередь» → «Проверено»). Commit: `docs: результаты экспериментов по метке и domainStrategy`.

---

## Этап 3. Основа и IPv6

### Task 3.1: Помощник: действия `firewall-apply` и `firewall-remove`

**Files:**
- Modify: `core/scripts/tun_route_helper.sh` (перед `*)`)
- Test: `tests/test_sys_tun_helper_script.py` (новый)

**Step 1: Тесты** — запускают sh-скрипт с подменёнными `id` и `nft` в `PATH`:

```python
"""Помощник tun-route-helper: правила nftables собирает он сам, по аргументам."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "core/scripts/tun_route_helper.sh"


@pytest.fixture
def fakebin(tmp_path):
    """`id` отвечает root, `nft` записывает stdin и аргументы."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "id").write_text("#!/bin/sh\necho 0\n")
    (bindir / "nft").write_text(
        '#!/bin/sh\necho "$@" >> "$FAKE_NFT_LOG"\ncat >> "$FAKE_NFT_LOG"\n'
    )
    for name in ("id", "nft"):
        (bindir / name).chmod((bindir / name).stat().st_mode | stat.S_IEXEC)
    return bindir


def run_helper(fakebin, tmp_path, *args):
    log = tmp_path / "nft.log"
    env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "FAKE_NFT_LOG": str(log)}
    result = subprocess.run(["sh", str(HELPER), *args], env=env, capture_output=True, text=True)
    return result, (log.read_text() if log.exists() else "")


def test_apply_full_writes_one_atomic_script(fakebin, tmp_path):
    result, log = run_helper(
        fakebin, tmp_path, "firewall-apply", "full", "xray0", "tun0", "203.0.113.5,2001:db8::5", "closed"
    )

    assert result.returncode == 0, result.stderr
    assert log.startswith("-f -\n")
    assert "table inet veblock {" in log
    assert "flush table inet veblock" in log
    assert log.index("flush table") < log.index("chain output")
    assert 'oifname "xray0" accept' in log
    assert 'oifname "tun0" accept' in log
    assert "ip daddr { 203.0.113.5 } accept" in log
    assert "ip6 daddr { 2001:db8::5 } accept" in log
    assert "th dport 53 reject" in log
    assert "meta mark 0x7e6a accept" in log
    assert log.rstrip().endswith("}")
    assert "reject with icmpx type admin-prohibited" in log
    assert "nfproto ipv6" not in log


def test_apply_ipv6_only_touches_only_ipv6(fakebin, tmp_path):
    result, log = run_helper(fakebin, tmp_path, "firewall-apply", "ipv6_only", "xray0", "-", "-", "open")

    assert result.returncode == 0, result.stderr
    assert "meta nfproto ipv6 reject with icmpx type admin-prohibited" in log
    assert "dport 53" not in log
    assert 'oifname "tun0"' not in log


def test_apply_with_open_dns_has_no_dns_rule(fakebin, tmp_path):
    _, log = run_helper(fakebin, tmp_path, "firewall-apply", "full", "xray0", "-", "-", "open")
    assert "dport 53" not in log


@pytest.mark.parametrize(
    "args",
    [
        ("firewall-apply", "loose", "xray0", "-", "-", "closed"),
        ("firewall-apply", "full", "xray0; nft flush ruleset", "-", "-", "closed"),
        ("firewall-apply", "full", "xray0", "-", "not-an-ip", "closed"),
        ("firewall-apply", "full", "xray0", "-", "-", "maybe"),
        ("firewall-apply", "full", "xray0", "-", "-"),
    ],
)
def test_bad_arguments_are_refused_before_nft_runs(fakebin, tmp_path, args):
    result, log = run_helper(fakebin, tmp_path, *args)
    assert result.returncode == 1
    assert log == ""


def test_remove_tolerates_a_missing_table(fakebin, tmp_path):
    (fakebin / "nft").write_text("#!/bin/sh\nexit 1\n")
    result, _ = run_helper(fakebin, tmp_path, "firewall-remove")
    assert result.returncode == 0


def test_features_lists_firewall(fakebin, tmp_path):
    result, _ = run_helper(fakebin, tmp_path, "features")
    assert result.returncode == 0
    assert "firewall" in result.stdout.split()
```

**Step 2:** Run: `uv run pytest tests/test_sys_tun_helper_script.py -q -p no:cacheprovider --no-cov` → FAIL (`unknown action`, код 1, а `features`/`apply` не проходят)

**Step 3: Реализация** — в `core/scripts/tun_route_helper.sh` перед `*)`:

```sh
  features)
    # Что умеет этот помощник: приложение из исходников может работать
    # с помощником установленного пакета, который новых действий не знает.
    echo "apply restore dns firewall"
    ;;

  firewall-apply)
    # firewall-apply <full|ipv6_only> <tun_name> <vpn_if|-> <vpn_addrs(,)|-> <open|closed>
    # Правила собирает сам помощник: от root без пароля нельзя принимать
    # готовый текст. Скрипт для `nft -f` один: создать-если-нет, очистить,
    # наполнить — переустановка атомарна, щели с policy accept нет.
    [ $# -eq 5 ] || die "firewall-apply requires 5 args"
    level="$1"; tun_name="$2"; vpn_if="$3"; vpn_addrs="$4"; dns="$5"
    case "$level" in full|ipv6_only) ;; *) die "invalid level" ;; esac
    is_ifname "$tun_name" || die "invalid tun_name"
    [ "$vpn_if" = "-" ] || is_ifname "$vpn_if" || die "invalid vpn_if"
    case "$dns" in open|closed) ;; *) die "invalid dns state" ;; esac
    v4=""; v6=""
    if [ "$vpn_addrs" != "-" ]; then
      for addr in $(echo "$vpn_addrs" | tr ',' ' '); do
        if is_ipv4 "$addr"; then v4="$v4${v4:+, }$addr"
        elif is_ipv6 "$addr"; then v6="$v6${v6:+, }$addr"
        else die "invalid vpn address"; fi
      done
    fi
    command -v nft >/dev/null 2>&1 || die "nft not found"
    {
      echo 'table inet veblock {}'
      echo 'flush table inet veblock'
      echo 'table inet veblock {'
      echo '  comment "Veblock: traffic block on connection loss; remove: nft delete table inet veblock"'
      for chain in output forward; do
        echo "  chain $chain {"
        echo "    type filter hook $chain priority 0; policy accept;"
        [ "$chain" = output ] && echo '    oif "lo" accept'
        [ "$chain" = output ] && echo '    meta mark 0x7e6a accept'
        echo "    oifname \"$tun_name\" accept"
        [ "$vpn_if" = "-" ] || echo "    oifname \"$vpn_if\" accept"
        [ -z "$v4" ] || echo "    ip daddr { $v4 } accept"
        [ -z "$v6" ] || echo "    ip6 daddr { $v6 } accept"
        if [ "$level" = full ] && [ "$dns" = closed ]; then
          echo '    meta l4proto { tcp, udp } th dport 53 reject with icmpx type admin-prohibited'
        fi
        [ "$chain" = output ] && echo '    udp sport 68 udp dport 67 accept'
        echo '    icmpv6 type { nd-router-solicit, nd-neighbor-solicit, nd-neighbor-advert } accept'
        echo '    ip daddr { 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 224.0.0.0/4, 255.255.255.255 } accept'
        echo '    ip6 daddr { ::1/128, fc00::/7, fe80::/10, ff00::/8 } accept'
        if [ "$level" = full ]; then
          echo '    reject with icmpx type admin-prohibited'
        else
          echo '    meta nfproto ipv6 reject with icmpx type admin-prohibited'
        fi
        echo '  }'
      done
      echo '}'
    } | nft -f -
    ;;

  firewall-remove)
    [ $# -eq 0 ] || die "firewall-remove takes no args"
    command -v nft >/dev/null 2>&1 || exit 0
    nft delete table inet veblock 2>/dev/null || true
    ;;
```

Добавить `is_ipv6()`: `echo "$1" | grep -Eq '^[0-9a-fA-F:]{2,39}$' && case "$1" in *:*) return 0;; esac; return 1` (двоеточие обязательно, разрешены только hex и `:`; этого достаточно, чтобы строка не вырвалась из set-литерала nft). Адреса не могут содержать пробелы и фигурные скобки — проверка это гарантирует.

Внимание: `set -e` и `nft delete … || true` совместимы. `reject with icmpx` в `inet` работает и для IPv4, и для IPv6. Список локальных сетей продублирован из `LOCAL_NETWORKS` (`src/db/config.py:465`): помощник не читает Python; тест в Task 3.3 проверяет, что списки совпадают.

**Step 4:** Run: `uv run pytest tests/test_sys_tun_helper_script.py -q -p no:cacheprovider --no-cov` → PASS. Дополнительно синтаксис nft без root: `sh core/scripts/tun_route_helper.sh` нельзя (требует root), поэтому вытащить текст из лога теста и прогнать `nft -c -f <файл>`: `nft -c` проверяет синтаксис без применения — добавить это как тест с `pytest.mark.skipif(not shutil.which("nft"))`: записать лог без первой строки `-f -` во временный файл, `subprocess.run(["nft", "-c", "-f", path])`, ожидать код 0. На машине разработчика `nft` есть; `-c` не трогает систему.

**Step 5: Commit**

```bash
git add core/scripts/tun_route_helper.sh tests/test_sys_tun_helper_script.py
git commit -m "feat(sys): помощник ставит и снимает таблицу nftables"
```

### Task 3.2: `src/sys/linux/tun_firewall.py` и фасад

**Files:**
- Create: `src/sys/linux/tun_firewall.py`, `src/sys/windows/tun_firewall.py`, `src/sys/tun_firewall.py`
- Modify: `tests/test_sys_facades.py:11-18` (добавить `"tun_firewall"` в `FACADES`)
- Test: `tests/test_sys_tun_firewall.py`

**Step 1: Тесты**

```python
"""Политика блокировки трафика превращается в аргументы помощника."""

from __future__ import annotations

from src.sys.linux import tun_firewall
from src.sys.linux.tun_firewall import FirewallPolicy, Level


def test_ipv6_only_policy_arguments():
    policy = FirewallPolicy(level=Level.IPV6_ONLY, tun_name="xray0")
    assert policy.helper_args() == ["ipv6_only", "xray0", "-", "-", "open"]


def test_full_policy_with_vpn_and_closed_dns():
    policy = FirewallPolicy(
        level=Level.FULL,
        tun_name="xray0",
        vpn_interface="tun0",
        vpn_addresses=("203.0.113.5", "2001:db8::5"),
        dns_closed=True,
    )
    assert policy.helper_args() == ["full", "xray0", "tun0", "203.0.113.5,2001:db8::5", "closed"]


def test_apply_goes_through_the_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(tun_firewall, "_run_helper", lambda a, args, timeout=15: calls.append((a, args)) or (True, ""))
    ok, err = tun_firewall.apply_firewall(FirewallPolicy(level=Level.IPV6_ONLY, tun_name="xray0"))
    assert (ok, err) == (True, "")
    assert calls == [("firewall-apply", ["ipv6_only", "xray0", "-", "-", "open"])]


def test_apply_without_helper_tries_sudo_nft_without_a_prompt(monkeypatch):
    """Из исходников помощника нет: один вызов sudo -n nft -f -, пароль не спрашиваем."""
    commands = []
    monkeypatch.setattr(tun_firewall, "_run_helper", lambda *a, **k: (False, "helper not installed"))
    monkeypatch.setattr(tun_firewall, "_run_stdin", lambda cmd, text, timeout=15: commands.append((cmd, text)) or (True, ""))
    monkeypatch.setattr(tun_firewall.shutil, "which", lambda name: f"/usr/sbin/{name}")
    ok, _ = tun_firewall.apply_firewall(FirewallPolicy(level=Level.IPV6_ONLY, tun_name="xray0"))
    assert ok
    assert commands[0][0] == ["sudo", "-n", "/usr/sbin/nft", "-f", "-"]
    assert "table inet veblock" in commands[0][1]


def test_remove_is_quiet_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(tun_firewall, "_run_helper", lambda *a, **k: (False, "helper not installed"))
    monkeypatch.setattr(tun_firewall.shutil, "which", lambda name: None)
    assert tun_firewall.remove_firewall() == (True, "")


def test_rendered_local_networks_match_the_routing_list():
    """Список локальных сетей в помощнике и в LOCAL_NETWORKS один и тот же."""
    from pathlib import Path

    from src.db.config import LOCAL_NETWORKS

    helper = Path("core/scripts/tun_route_helper.sh").read_text()
    for network in LOCAL_NETWORKS:
        assert network in helper
```

Запасной путь без помощника (`sudo -n nft -f -`) нужен только разработчику из исходников; текст для него строит `render_ruleset(policy)` в Python — да, это второй рендерер. Чтобы они не разошлись, добавить тест: текст `render_ruleset` для политики из `test_apply_full_writes_one_atomic_script` построчно (без пробелов) совпадает с тем, что пишет помощник в фейковый `nft`. Если это кажется лишним — убрать запасной путь целиком и `tun_problems` будет говорить «установите пакет»; решение принять при реализации, по умолчанию — убрать запасной путь (YAGNI), тогда `test_apply_without_helper_…` заменить на «без помощника — отказ с текстом».

**Step 2:** Run: `uv run pytest tests/test_sys_tun_firewall.py tests/test_sys_facades.py -q -p no:cacheprovider --no-cov` → FAIL `ModuleNotFoundError`

**Step 3: Реализация** `src/sys/linux/tun_firewall.py`:

```python
"""Блокировка трафика мимо туннеля таблицей nftables `inet veblock`.

Таблицу ставит root-помощник по проверенным аргументам (см.
tun_route_helper.sh). Уровень `ipv6_only` стоит в любом сеансе TUN: IPv6 в
туннель не заворачивается и иначе ходит мимо прокси. Уровень `full` — настройка
«Блокировать трафик при обрыве»: закрыт весь прямой трафик, кроме локальной
сети, сокетов ядра (метка) и VPN сервера.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import StrEnum

from src.sys.linux.tun_route import _run_helper

logger = logging.getLogger("tenga.sys.tun_firewall")

# Метка сокетов ядра: её же ждёт правило `meta mark` помощника.
SOCKET_MARK = 0x7E6A
TABLE = "inet veblock"


class Level(StrEnum):
    IPV6_ONLY = "ipv6_only"
    FULL = "full"


@dataclass(frozen=True)
class FirewallPolicy:
    level: Level
    tun_name: str
    vpn_interface: str | None = None
    vpn_addresses: tuple[str, ...] = ()
    dns_closed: bool = False

    def helper_args(self) -> list[str]:
        return [
            str(self.level),
            self.tun_name,
            self.vpn_interface or "-",
            ",".join(self.vpn_addresses) or "-",
            "closed" if self.dns_closed else "open",
        ]


def apply_firewall(policy: FirewallPolicy) -> tuple[bool, str]:
    ok, err = _run_helper("firewall-apply", policy.helper_args())
    if ok:
        logger.info("Firewall applied: %s", policy.helper_args())
        return True, ""
    return False, err


def remove_firewall() -> tuple[bool, str]:
    """Снять таблицу; её отсутствие — не ошибка."""
    ok, err = _run_helper("firewall-remove", [])
    if ok or "helper not installed" in err and not shutil.which("nft"):
        return True, ""
    if "helper not installed" in err:
        return True, ""  # без помощника таблицу никто и не ставил
    return False, err


def firewall_available(which=shutil.which) -> bool:
    return which("nft") is not None
```

Упростить `remove_firewall` по итогам решения о запасном пути. Фасад `src/sys/tun_firewall.py` по образцу `src/sys/tun_route.py`; `src/sys/windows/tun_firewall.py` — те же имена, `apply_firewall` возвращает `(True, "")` с комментарием «служба Windows блокировку пока не ставит», `Level` и `FirewallPolicy` импортировать из `src/sys/linux/tun_firewall`? Нет — Linux-модуль тянет `tun_route`, а тот `CORE_DIR`; это импортируется и на Windows (так делают тесты), значит можно. Но чище вынести `Level`/`FirewallPolicy` в `src/sys/firewall_policy.py` без зависимостей и импортировать в обе реализации.

**Step 4:** Run: `uv run pytest tests/test_sys_tun_firewall.py tests/test_sys_facades.py -q -p no:cacheprovider --no-cov` → PASS

**Step 5: Commit** `feat(sys): фасад блокировки трафика tun_firewall`

### Task 3.3: Метка и `domainStrategy` на outbound в TUN

**Files:**
- Modify: `src/core/config_builder.py:107-109` (`_bind_to_interface`), `:326-346`, `:386-400`
- Test: `tests/test_core_tun_outbounds.py`

**Step 1: Тесты** (фикстуры `context`, `profile`, `physical`, хелпер `outbound` уже есть в файле):

```python
def sockopt(config, tag):
    return outbound(config, tag).get("streamSettings", {}).get("sockopt", {})


def test_tun_marks_every_socket_outbound(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN
    config = build_session_config(context, profile)
    for tag in ("proxy", "direct", "dns-out"):
        assert sockopt(config, tag)["mark"] == 0x7E6A, tag


def test_system_proxy_mode_does_not_mark(context, profile):
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
    config = build_session_config(context, profile)
    assert "mark" not in sockopt(config, "proxy")


def test_tun_resolves_the_server_name_through_the_core_dns(context, physical):
    """Иначе имя сервера уходит системному резолверу без метки — под блокировку."""
    context.config.proxy_mode = ProxyMode.TUN
    named = make_profile(context, VLESS_LINK.replace("<ip>", "proxy.example.com"))  # см. tests/support/session.py: подобрать ссылку с доменом
    config = build_session_config(context, named)
    assert sockopt(config, "proxy")["domainStrategy"] == "UseIPv4"


def test_ip_server_needs_no_domain_strategy(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN
    config = build_session_config(context, profile)
    assert "domainStrategy" not in sockopt(config, "proxy")
```

Проверить `tests/support/session.py::VLESS_LINK` и теги outbound'ов (`proxy` — тег основного? посмотреть `outbound["tag"]` в `config_builder` около строки 300) и поправить имена в тестах.

**Step 2:** Run → FAIL (`KeyError: 'mark'`)

**Step 3: Реализация** в `config_builder.py`:

```python
from src.sys.firewall_policy import SOCKET_MARK  # или откуда вынесена константа


def _mark_socket(outbound: dict) -> None:
    """Метка сокета: правило nftables пропускает трафик ядра мимо блокировки."""
    sockopt = outbound.setdefault("streamSettings", {}).setdefault("sockopt", {})
    sockopt["mark"] = SOCKET_MARK
```

В сборке outbound'ов после привязки к интерфейсу: `if runtime_mode == ProxyMode.TUN: for o in (outbound, direct_outbound, dns_outbound?, vpn_outbound?): _mark_socket(o)` — там, где каждый создаётся (dns-out и vpn создаются ниже; пометить каждый на месте создания, условие `tun_mode`). На proxy-outbound, если `profile.bean.server_address` — не IP и не loopback: `sockopt["domainStrategy"] = "UseIPv4"`. Проверить, что `config_validator.py` не отвергает `mark`/`domainStrategy` (прогнать все тесты).

Значение `SOCKET_MARK` должно совпадать с `0x7e6a` в помощнике: добавить в `tests/test_sys_tun_firewall.py` проверку `f"0x{SOCKET_MARK:x}" in helper_text`.

**Step 4:** Run: `uv run pytest tests/test_core_tun_outbounds.py tests/test_core_config_builder.py tests/test_core_config_validator.py -q -p no:cacheprovider --no-cov` → PASS

**Step 5: Commit** `feat(core): метка сокетов и внутренний резолв имени сервера в TUN`

### Task 3.4: Убрать мёртвые ключи `autoRoute`/`strictRoute`

**Files:** `src/core/proxy_mode.py:48-53`, `tests/test_core_proxy_mode.py:40-41`

Удалить два ключа и две строки assert; добавить комментарий у `settings`: «`autoRoute`/`strictRoute` — ключи sing-box, Xray их игнорирует: маршрут и блокировку ставит приложение». Run: `uv run pytest tests/test_core_proxy_mode.py -q` → PASS. Commit `chore(core): убрать ключи sing-box из TUN-inbound`.

### Task 3.5: `ConnectionService` ставит `ipv6_only` и снимает при отключении

**Files:**
- Modify: `src/core/connection.py` (`connect`, `disconnect`, `handle_core_exit`, `ConnectionResult`)
- Modify: `src/ui/controller.py:381-391` (`_on_connection_done`: тост `result.warning`)
- Test: `tests/test_core_connection.py`, `tests/test_ui_controller.py`

**Step 1: Тесты**

```python
def _tun_context(tmp_path, monkeypatch, profile=None):
    context = make_context(tmp_path, profile or FakeProfile())
    context.config.proxy_mode = "tun"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.intercepts_dns", lambda _c: False)
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, "state", ""))
    monkeypatch.setattr("src.core.connection.restore_tun_routes", lambda _s: (True, ""))
    return context


def test_tun_connect_blocks_ipv6_before_starting_the_core(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    order = []
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda p: order.append(("fw", p.level, p.tun_name)) or (True, ""))
    context.xray_manager.start.side_effect = lambda _c: order.append(("start",)) or (True, "")

    assert ConnectionService(context).connect(1).ok
    assert order == [("fw", "ipv6_only", "xray0"), ("start",)]


def test_ipv6_block_failure_is_a_warning_not_an_error(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda p: (False, "nft not found"))

    result = ConnectionService(context).connect(1)

    assert result.ok
    assert "IPv6" in result.warning and "nft not found" in result.warning


def test_disconnect_removes_the_firewall_right_after_the_core(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    context.proxy_state.is_running = True
    context.proxy_state.started_mode = "tun"
    order = []
    context.xray_manager.stop.side_effect = lambda: order.append("stop") or (True, "")
    monkeypatch.setattr("src.core.connection.remove_firewall", lambda: order.append("fw-remove") or (True, ""))
    monkeypatch.setattr("src.core.connection.restore_tun_routes", lambda _s: order.append("routes") or (True, ""))

    ConnectionService(context).disconnect()

    assert order == ["stop", "fw-remove", "routes"]


def test_core_exit_keeps_the_firewall(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    context.proxy_state.started_mode = "tun"
    removed = []
    monkeypatch.setattr("src.core.connection.remove_firewall", lambda: removed.append(True) or (True, ""))
    ConnectionService(context).handle_core_exit()
    assert removed == []


def test_system_proxy_mode_does_not_touch_the_firewall(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda p: (_ for _ in ()).throw(AssertionError("called")))
    assert ConnectionService(context).connect(1).ok
```

Существующие тесты `make_context` ставят `proxy_mode = "system_proxy"`, поэтому не ломаются; тесты с `tun` в `tests/test_core_connection*.py` нужно дополнить `monkeypatch` на `apply_firewall`/`remove_firewall` — пройтись по падениям.

**Step 2:** Run → FAIL (`AttributeError: module 'src.core.connection' has no attribute 'apply_firewall'`)

**Step 3: Реализация**

```python
from src.sys.firewall_policy import FirewallPolicy, Level
from src.sys.tun_firewall import apply_firewall, remove_firewall

IPV6_BLOCK_WARNING = "IPv6 не заблокирован, трафик по нему может идти мимо прокси: {error}"


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    error: str = ""
    # Подключение состоялось, но с оговоркой, которую пользователю надо показать.
    warning: str = ""
```

В `connect()` перед `context.xray_manager.start(config)`:

```python
warning = ""
if runtime_mode == ProxyMode.TUN:
    warning = self._block_traffic(settings)
```

```python
def _block_traffic(self, settings) -> str:
    """Таблица nftables до запуска ядра: окна, когда трафик идёт мимо, нет.

    Возвращает предупреждение, если уровень ipv6_only поставить не удалось:
    блокировку пользователь не включал, срывать подключение нельзя.
    """
    policy = FirewallPolicy(level=Level.IPV6_ONLY, tun_name=getattr(settings, "tun_name", "xray0"))
    ok, error = apply_firewall(policy)
    if ok:
        return ""
    logger.warning("IPv6 block not applied: %s", error)
    return IPV6_BLOCK_WARNING.format(error=error)
```

Возвращать `ConnectionResult(True, warning=warning)`. При неудаче старта ядра или маршрутов в TUN — `remove_firewall()` (первое подключение не состоялось). В `disconnect()` — `remove_firewall()` сразу после `xray_manager.stop()`, до `_auto_disconnect_vpn()` и `_undo_runtime_mode()`; выполнять, если `started_mode == TUN`. В `handle_core_exit` — не трогать. В `_on_connection_done` контроллера: `if result.ok and result.warning: self.toast(result.warning)`.

**Step 4:** Run: `uv run pytest tests/test_core_connection*.py tests/test_ui_controller.py -q -p no:cacheprovider --no-cov` → PASS

**Step 5: Commit** `feat(core): блокировать IPv6 в каждом сеансе TUN`

### Task 3.6: Снятие таблицы при старте и `tun_problems`

**Files:**
- Modify: `gui.py:85-99` (`recover_network`)
- Modify: `src/sys/linux/tun_access.py:48-96`
- Test: `tests/test_sys_tun_access.py`, тест `recover_network` (найти существующий: `grep -rn recover_network tests`)

**Step 1: Тесты** для `tun_problems` (по образцу существующих в `tests/test_sys_tun_access.py`, где `sudo_allows`, `exists`, `which` подменяются):

```python
def test_missing_nft_is_reported():
    problems = tun_access.tun_problems(
        None, geteuid=lambda: 1000, sudo_allows=lambda _c: True,
        exists=lambda _p: True, which=lambda name: None if name == "nft" else f"/usr/bin/{name}",
        helper_features=lambda: {"apply", "restore", "dns", "firewall"},
    )
    assert any("nftables" in p for p in problems)


def test_old_helper_without_firewall_is_reported():
    problems = tun_access.tun_problems(
        None, geteuid=lambda: 1000, sudo_allows=lambda _c: True,
        exists=lambda _p: True, which=lambda name: f"/usr/bin/{name}",
        helper_features=lambda: {"apply", "restore", "dns"},
    )
    assert any("firewall" in p or "обновите" in p.lower() for p in problems)


def test_root_still_needs_nft():
    problems = tun_access.tun_problems(None, geteuid=lambda: 0, which=lambda name: None)
    assert len(problems) == 1 and "nftables" in problems[0]
```

**Step 2:** FAIL (`unexpected keyword argument 'helper_features'`)

**Step 3: Реализация**: параметр `helper_features: Callable[[], set[str]] = _helper_features`, где `_helper_features()` запускает `sudo -n HELPER_PATH features` (если помощник есть) и возвращает `set(stdout.split())`, при ошибке — пустое множество. Тексты: «Нет nftables: без него IPv6 и блокировка трафика при обрыве не работают. Выполните: sudo apt install nftables»; «Установленный помощник tun-route-helper старый, без действия firewall: sudo apt install --reinstall tenga-proxy». Проверка `nft` — до `if geteuid() == 0: return []`, то есть и для root.

`recover_network()` в `gui.py`: после `recover_tun_routes()` — `from src.sys.tun_firewall import remove_firewall; ok, error = remove_firewall()`; результат «снята ли таблица» помощник не сообщает (`delete … || true`), поэтому уведомление пользователю отложено до этапа 4, где снятие делается по журналу состояния. Здесь — только снятие и запись в лог.

**Step 4:** Run → PASS. **Step 5: Commit** `feat(sys): проверка nftables в диагностике TUN, снятие таблицы при старте`

### Task 3.7: Пакет: зависимость, `prerm`, sudoers

**Files:** `core/scripts/build_deb.sh:122`, `packaging/linux/prerm`, `packaging/linux/sudoers`

1. `Depends: … iproute2, sudo, nftables`.
2. `prerm`:

```sh
#!/bin/sh
set -e

# Таблица блокировки общесистемная и живёт в памяти: при удалении пакета её
# больше некому снять. При обновлении не трогаем — у пользователя может идти
# сеанс с включённой блокировкой.
case "$1" in
  remove|purge)
    command -v nft >/dev/null 2>&1 && nft delete table inet veblock 2>/dev/null || true
    ;;
esac

# Байт-код собирал postinst, dpkg о нём не знает и каталоги без него не удалит.
find /usr/lib/tenga-proxy -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

exit 0
```

3. Комментарий в `sudoers`: «Помощник принимает только apply, restore, dns, features, firewall-apply и firewall-remove и сам проверяет аргументы».
4. Проверка: `python cli.py build` собирает пакет; `dpkg-deb -I dist/tenga-proxy_*.deb | grep Depends` содержит `nftables`. Установку на машине разработчика можно сделать (`python cli.py install`), но **не подключаться** в TUN до конца этапа — сеанс уже идёт установленной версией; лучше проверять в виртуалке.
5. Commit `build(deb): зависимость nftables и снятие таблицы при удалении`

### Task 3.8: `make test-firewall`: настоящие правила в сетевом пространстве

**Files:**
- Create: `tests/firewall/test_nft_rules.py`, `tests/firewall/__init__.py`
- Modify: `Makefile` (цель), `pyproject.toml:68-72` (маркер `firewall`), `.github/workflows/linux.yml` (шаг после `make test-tray`, `APT_PACKAGES` + `nftables`)

Тест запускается только внутри `unshare -n` от root (проверка: `os.geteuid() == 0` и переменная `TENGA_FIREWALL_TESTS=1`, иначе `pytest.skip`). Сценарий:

```python
@pytest.fixture
def lab():
    run("ip link add d0 type dummy"); run("ip link set d0 up"); run("ip addr add 10.0.0.2/24 dev d0")
    run("ip link add x0 type dummy"); run("ip link set x0 up")
    run("ip route add default via 10.0.0.1 dev d0 metric 600")
    run("ip -6 addr add 2001:db8::2/64 dev d0 nodad"); run("ip -6 route add default via 2001:db8::1 dev d0")
    yield
    run("nft delete table inet veblock", check=False)


def connect_errno(addr, port=443, family=socket.AF_INET):
    s = socket.socket(family, socket.SOCK_STREAM); s.settimeout(2)
    try:
        s.connect((addr, port)); return 0
    except OSError as e:
        return e.errno
    finally:
        s.close()


def test_ipv6_only_rejects_ipv6_and_leaves_ipv4(lab):
    helper("firewall-apply", "ipv6_only", "x0", "-", "-", "open")
    assert connect_errno("2001:db8:1::1", family=socket.AF_INET6) in (errno.EACCES, errno.EHOSTUNREACH, errno.ECONNREFUSED)
    assert connect_errno("203.0.113.1") in (0, errno.ETIMEDOUT)  # не reject: dummy молчит, но пакет вышел


def test_full_rejects_direct_but_allows_lan_and_marked(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")
    assert connect_errno("203.0.113.1") in (errno.EACCES, errno.EHOSTUNREACH)
    assert connect_errno("10.0.0.9", port=22) == errno.ETIMEDOUT  # ушёл, ответа нет
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, 0x7E6A); s.settimeout(1)
    with pytest.raises(socket.timeout):  # помечен — пропущен, dummy молчит
        s.connect(("203.0.113.1", 443))


def test_reapply_keeps_blocking_without_a_gap(lab):
    """Переустановка — один скрипт: между open и closed состояния accept нет."""
    helper("firewall-apply", "full", "x0", "-", "-", "open")
    helper("firewall-apply", "full", "x0", "-", "-", "closed")
    ruleset = run("nft list table inet veblock").stdout
    assert ruleset.count("chain output") == 1 and "dport 53" in ruleset


def test_remove_is_idempotent(lab):
    helper("firewall-remove"); helper("firewall-remove")
    assert "veblock" not in run("nft list ruleset").stdout
```

`helper(...)` вызывает `sh core/scripts/tun_route_helper.sh` напрямую (мы root). `ETIMEDOUT` при `settimeout(2)` приходит как `socket.timeout`/`TimeoutError` — обработать: вернуть `errno.ETIMEDOUT`.

Makefile:

```make
# Настоящие правила nftables: в отдельном сетевом пространстве, от root.
# AppArmor Ubuntu не пускает непривилегированные user namespaces, поэтому sudo.
test-firewall:
	sudo -E env TENGA_FIREWALL_TESTS=1 PATH="$$PATH" unshare -n \
		uv run pytest -m firewall tests/firewall -p no:cacheprovider --no-cov -q
```

`pyproject.toml`: маркер `"firewall: real nftables in a network namespace, run through make test-firewall"`, и в `addopts`/`-m` по умолчанию исключить `firewall` так же, как исключены `gtk`/`qt` (посмотреть, как это сделано: `grep -n "addopts\|-m " pyproject.toml`). CI: шаг `sudo apt-get install nftables` уже через `APT_PACKAGES`, затем `make test-firewall` (GitHub runner даёт sudo без пароля; `unshare -n` там работает).

Прогнать локально: `make test-firewall` — безопасно для живого сеанса, пространство имён отдельное. Commit `test(sys): настоящие правила nftables в сетевом пространстве`.

### Task 3.9: Документация этапа

- `CLAUDE.md`, раздел «TUN на Linux»: абзац про `tun_firewall`, таблицу `inet veblock`, метку, `make test-firewall`, запрет запускать на машине разработчика.
- `docs/ru/routing.md` и `docs/en/routing.md` (или `vpn.md`): «В режиме TUN IPv6 блокируется; сайты только с IPv6 недоступны; ручное снятие `sudo nft delete table inet veblock`».
- Commit `docs: блокировка IPv6 в TUN`.

Этап 3 можно выпустить: версия через `python cli.py bump-version`, примечание к выпуску про IPv6.

---

## Этап 4. Уровень `full`

Задачи этого этапа зависят от результатов этапа 2; код ниже — ориентир, тесты обязательны по той же схеме (падающий тест → реализация → прогон → коммит).

### Task 4.1: Настройка `tun_kill_switch`

**Files:** `src/db/data_store.py:37-39` (поле `tun_kill_switch: bool = False` рядом с `tun_*`; проверить, что `to_dict`/`from_dict` берут поля автоматически — `grep -n "def to_dict" -A10 src/db/data_store.py`), `src/ui/logic/settings_state.py:8-16` (`_RUNTIME_KEYS` + `"tun_kill_switch"`), тесты `tests/test_db_*`, `tests/test_ui_logic_settings_state.py` (снапшот меняется при смене флага). Commit `feat(db): настройка блокировки трафика при обрыве`.

### Task 4.2: Адреса VPN-сервера из NetworkManager

**Files:** `src/sys/linux/vpn.py` (новая `vpn_server_addresses(connection_name) -> tuple[str, ...]` и `vpn_connection_type(name) -> str`), `src/sys/windows/vpn.py` (заглушки), `src/sys/vpn.py` (фасад), `tests/test_sys_vpn*.py`.

Реализация: `nmcli -g connection.type connection show <name>` → `vpn`/`wireguard`/`tun`; для `vpn`: `nmcli -g vpn.data connection show <name>` → пары `key = value` через запятую; взять `remote` (OpenVPN: `host[:port]`, несколько через пробел или запятую) или `gateway` (другие плагины); каждое значение через `socket.getaddrinfo` → уникальные IPv4 и IPv6. Запасной источник: `ip route show` — маршруты `/32` с `proto static` через физический интерфейс, появившиеся у подключения (сложнее; делать только если `vpn.data` пуст). Тесты с подменённым `subprocess.run` и `getaddrinfo`.

### Task 4.3: Разделить `connect()` на `_teardown` и `disconnect()`

**Files:** `src/core/connection.py`, `tests/test_core_connection.py`.

- `connect()` при `is_running` зовёт `self._teardown(keep_block=True)`: `xray_manager.stop()`, `_undo_runtime_mode()`, `set_stopped()`, монитор стоп; VPN и таблицу не трогает.
- `disconnect()` = `_teardown(keep_block=False)` + `_auto_disconnect_vpn()`; порядок: stop → `remove_firewall()` → маршруты → VPN.
- `XrayManager.start()` при работающем ядре больше не должен молча перезапускать: оставить как есть (страховка), но `connect()` всегда делает `_teardown` первым.
- Тесты: смена сервера не зовёт `remove_firewall` и `disconnect_vpn`; `disconnect` зовёт оба; порядок при `disconnect`.

### Task 4.4: Политика `full` при подключении

**Files:** `src/core/connection.py`, `tests/test_core_connection.py`.

В `_block_traffic(settings, profile)`:

```python
level = Level.FULL if getattr(settings, "tun_kill_switch", False) else Level.IPV6_ONLY
if level is Level.FULL:
    refusal = self._kill_switch_refusal(settings, profile)   # перехват DNS выключен / VPN wireguard|tun / адрес VPN не найден / nft нет
    if refusal:
        return refusal  # ConnectionResult(False, …) — подключение отменяется
policy = FirewallPolicy(level, tun_name, vpn_interface, vpn_addresses, dns_closed=False)
```

Тексты отказов: «Блокировка трафика при обрыве требует перехвата DNS: включите его в настройках DNS или выключите блокировку», «Блокировка трафика при обрыве не поддерживает VPN типа WireGuard: выключите блокировку или VPN у сервера», «Не удалось узнать адрес VPN-сервера «…»: блокировка закрыла бы сам VPN». Ошибка применения `full` — отказ с текстом помощника плюс подсказка `tun_problems`.

После `route_system_dns_to_tun` успешен → `apply_firewall(replace(policy, dns_closed=True))`; неуспешен → `proxy_state.dns_unprotected = True` (новое поле) и предупреждение в `ConnectionResult.warning`: «DNS не защищён: без systemd-resolved запросы при обрыве уйдут напрямую».

Первое подключение не удалось (ядро, маршруты) → `remove_firewall()`, как в 3.5; смена сервера не удалась → таблица остаётся, `proxy_state.traffic_blocked = True`.

### Task 4.5: Флаг `traffic_blocked` и `release_block()`

**Files:** `src/core/context.py:20-70` (`ProxyState.traffic_blocked: bool = False`, `dns_unprotected: bool = False`; `set_stopped()` их **не** сбрасывает — сбрасывает `ConnectionService`), `src/core/connection.py` (`release_block()`: `remove_firewall()`, `traffic_blocked = False`, `_auto_disconnect_vpn()`; `handle_core_exit()` ставит `traffic_blocked = settings.tun_kill_switch`), `src/core/core_pid.py` или новый журнал `CORE_DIR/firewall.json` с записью `{"level": …}` при `apply` и удалением при `remove` — чтобы `recover_network()` знал, что снял именно нашу блокировку, и контроллер показал «Прошлый сеанс завершился сбоем, блокировка трафика снята». Тесты на каждую ветку.

### Task 4.6: Контроллер: BLOCKED после неудачного перезапуска, `release-block`

**Files:** `src/ui/controller.py`, `tests/test_ui_controller.py`.

- `_on_core_exit`: при `traffic_blocked` после отказа от перезапуска — `notify_user("Соединение потеряно. Трафик закрыт, локальная сеть доступна")`, `set_tray_state(ConnectionState.BLOCKED, name)`; `_on_connection_done` при неудаче и `traffic_blocked` — то же.
- `release_block()`: фоновый `service.release_block()`, тост «Блокировка снята».
- `toggle_connection()`: если `traffic_blocked and not is_running` → `connect_profile(last_blocked_profile_id)`; хранить id в `proxy_state.started_profile_id` (не сбрасывать в `set_stopped`? Проверить: сейчас `set_stopped` ставит `-1`; добавить `blocked_profile_id`).
- Запуск: `gui.py::recover_network()` возвращает `released: bool`; передать контроллеру через `AppContext` (например `context.startup_notes: list[str]`), контроллер показывает при старте окна.

### Task 4.7: Документация этапа

`docs/plans/2026-11-03-tun-kill-switch-design.md` → статус «реализовано до этапа 4»; `docs/ru/routing.md`: раздел «Блокировка трафика при обрыве» (что закрыто, что открыто, VPN и WireGuard, captive portal, ручное снятие). Commit.

---

## Этап 5. Интерфейс GTK и Qt

### Task 5.1: `ConnectionState.BLOCKED` и `status_view`

**Files:** `src/ui/logic/status.py:15-26, 83-170, 258`, `tests/test_ui_logic_status.py`.

- `BLOCKED = "blocked"`; `status_view(BLOCKED)` → `StatusView(title="Трафик заблокирован", subtitle=profile_name, icon_name="dialog-warning-symbolic", css_class="status-blocked", button_label="Переподключить", logo_desaturated=True, …)`; `action_hint` для `status-blocked`: «Подключить сервер прошлого сеанса».
- `ConnectionPresentation.resolve(..., blocked: bool = False)`: `if blocked and not running: return status_view(BLOCKED, …)` до ветки ERROR.
- Тесты: заголовок, кнопка, что `blocked` важнее `error`, что при `running` BLOCKED не показывается.

### Task 5.2: Общий дизайн и трей

**Files:** `docs/plans/2026-11-02-shared-ui-design.md` (таблица «Состояния»: строка «Трафик заблокирован | сервер прошлого сеанса | «Переподключить» | предупреждение»; баннер; действие `release-block`), `src/ui/tray/menu.py` (пункт «Снять блокировку» в состоянии BLOCKED), `src/ui/tray/icons*.py` (значок для BLOCKED: тот же, что ERROR, если отдельного нет), `tests/test_ui_tray_menu.py`, `tests/test_ui_tray_icons.py`.

### Task 5.3: GTK

**Files:** `src/ui/application.py` (действие `release-block`), `src/ui/window.py` (баннер «Соединение потеряно. Трафик закрыт, локальная сеть доступна» с кнопкой «Снять блокировку» — второй `Adw.Banner` или общий баннер с приоритетом: BLOCKED важнее «Изменения применятся…»), `src/ui/widgets/status_card.py` (css-класс `status-blocked`), `src/ui/dialogs/settings.py:150-170` (`Adw.SwitchRow` «Блокировать трафик при обрыве», подсказка из дизайна, `set_sensitive(tun)` в `_sync_mode`), `src/ui/logic/settings_form.py` (условие показа: `kill_switch_row_visible()` → `not IS_WINDOWS`, в `src/ui/logic/platform_texts.py`), тесты `tests/test_ui_dialogs_settings.py`, `tests/test_ui_window.py`, `tests/test_ui_widgets_status_card.py` (`make test-gtk`).

### Task 5.4: Qt

**Files:** `src/ui/qt/application.py` (`QAction` `release-block`), `src/ui/qt/window.py` (баннер), `src/ui/qt/dialogs/settings.py:218-230, 376, 417-422` (`QCheckBox`, `setEnabled(tun)`, скрыт по `platform_texts`), `src/ui/qt/status_card.py`, тесты `tests/test_ui_qt_settings.py`, `tests/test_ui_qt_window*.py` (`make test-qt`). Проверить `tests/test_ui_platform_branches.py`: `IS_WINDOWS` виджеты не читают.

### Task 5.5: Документация и выпуск

- `CLAUDE.md`: раздел «TUN на Linux» — настройка, состояние BLOCKED, `release-block`.
- `docs/ru/gui.md`, `docs/en/gui.md`: настройка и состояние.
- `tests/test_branding.py` — убедиться, что новые тексты не содержат «Tenga Proxy».
- `python cli.py bump-version X.Y.0`; примечания: IPv6 закрыт в TUN, новая настройка, обработка падения ядра, ручное снятие таблицы.

---

## Проверка перед каждым коммитом

```bash
uv run python cli.py lint-all
uv run pytest -q -p no:cacheprovider --no-cov
```

Перед выпуском этапа: `make test-gtk`, `make test-qt`, `make test-tray`, `make test-firewall`, ручная проверка из дизайна в виртуалке.
