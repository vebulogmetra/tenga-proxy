# UI Redesign (GTK4 + libadwaita) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Дизайн и решения: `docs/plans/2026-09-02-ui-redesign-design.md` (читать первым).

**Goal:** Перевести GUI Tenga Proxy на GTK4 + libadwaita по GNOME HIG с полным функциональным паритетом и устранить дефекты UI (B1–B20 из дизайн-документа).

**Architecture:** Этап 0 чинит логику, не зависящую от GTK, прямо в `develop` (гонки тестов задержки, сигналы, монитор, дубли, валидация диалогов, single instance). Этапы 1–5 идут в ветке `feature/ui-adwaita`: новая оболочка `Adw.Application`/`Adw.ApplicationWindow`, страницы на `ColumnView`/`ListBox`/`PreferencesPage`, диалоги на `Adw.Dialog`/`Adw.PreferencesDialog`, трей на StatusNotifierItem через D-Bus, обновление сборки AppImage. Чистая логика живёт в `src/ui/logic` и `src/ui/models/filters.py` и тестируется без дисплея; виджеты тестируются под `xvfb-run`.

**Tech Stack:** Python 3.11, PyGObject, GTK 4.14, libadwaita 1.5, Gio.DBus, pytest, ruff, uv.

**Оценка объёма** (ориентир, рабочие дни одного разработчика):

| Этап | Содержание | Дни |
|------|------------|-----|
| 0 | Исправления логики в `develop` | 2 |
| 1 | Оболочка GTK4: приложение, окно, статус-карточка, тестовая инфраструктура | 3 |
| 2 | Страницы Профили / Подписки / Мониторинг, действия, тосты | 5 |
| 3 | Диалоги | 4 |
| 4 | Трей StatusNotifierItem | 3 |
| 5 | Сборка, документация, паритет, слияние | 2 |

Этапы 1–5 описаны на уровне задач с критериями приёмки и эскизами ключевого кода. Перед началом каждого из них выпускается детальный план по `superpowers:writing-plans` (файл `docs/plans/2026-MM-DD-ui-redesign-phase-N.md`), потому что точные сигнатуры виджетов зависят от результата предыдущего этапа.

**Правила для всех задач:**
- TDD: сначала падающий тест, затем минимальная реализация (`superpowers:test-driven-development`).
- Перед коммитом: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`.
- Коммиты маленькие, сообщения на английском в стиле репозитория (`fix:`, `feat:`, `refactor:`, `test:`).
- Никаких `subprocess`, сети или диска из обработчиков GTK в главном потоке.

---

## Этап 0. Исправления логики в `develop` — ВЫПОЛНЕН 2026-09-02

Ветка: `develop` (текущая). Старый GTK3 UI продолжает работать.

Коммиты: d5cf372, b98aa67, 4a7f465, 9718976, dbe2122, 812d8b8, 65eb046, f1101da.
Отклонения от плана: `format_bytes` сохранил два знака после запятой для ГБ
(план ожидал один — фактическое поведение важнее); тег первого outbound равен
имени профиля, а не строке `proxy`; в `ConnectionMonitor.stop()` добавлен сброс
флага, которого в плане не было.

### ✅ Task 0.1: LatencyRunner — ограниченный пул для тестов задержки (B1, B2)

**Files:**
- Create: `src/ui/logic/__init__.py` (пустой)
- Create: `src/ui/logic/latency.py`
- Create: `tests/test_ui_logic_latency.py`
- Modify: `src/ui/main_window.py:697-775` (`_on_test_delay_clicked`)

**Step 1: Write the failing test**

```python
# tests/test_ui_logic_latency.py
from __future__ import annotations

import threading
import time

from src.ui.logic.latency import LatencyRunner


def _collect(results: dict, done: list):
    def on_result(profile_id: int, latency_ms: int) -> None:
        results[profile_id] = latency_ms

    def on_done() -> None:
        done.append(True)

    return on_result, on_done


def test_runner_limits_concurrency_and_reports_every_profile():
    active = 0
    peak = 0
    lock = threading.Lock()

    def probe(profile_id: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return profile_id * 10

    delivered: list = []
    runner = LatencyRunner(probe, max_workers=2, dispatch=lambda fn, *a: delivered.append((fn, a)))
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([1, 2, 3, 4, 5], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}
    assert done == [True]
    assert peak <= 2


def test_runner_reports_minus_one_when_probe_raises():
    def probe(profile_id: int) -> int:
        raise RuntimeError("boom")

    delivered: list = []
    runner = LatencyRunner(probe, max_workers=1, dispatch=lambda fn, *a: delivered.append((fn, a)))
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([7], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {7: -1}
    assert done == [True]


def test_runner_rejects_second_run_while_busy():
    started = threading.Event()
    release = threading.Event()

    def probe(profile_id: int) -> int:
        started.set()
        release.wait(2)
        return 1

    runner = LatencyRunner(probe, max_workers=1, dispatch=lambda fn, *a: None)
    assert runner.run([1], on_result=lambda *_: None, on_done=lambda: None) is True
    started.wait(1)
    assert runner.run([2], on_result=lambda *_: None, on_done=lambda: None) is False
    release.set()
    runner.wait(timeout=5)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_logic_latency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ui.logic'`

**Step 3: Write minimal implementation**

```python
# src/ui/logic/latency.py
"""Bounded background runner for profile latency probes.

GTK-free: результаты доставляются через `dispatch` (по умолчанию GLib.idle_add),
чтобы модуль можно было тестировать без дисплея.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("tenga.ui.latency")

ProbeFn = Callable[[int], int]
ResultFn = Callable[[int, int], None]
DispatchFn = Callable[..., object]


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


class LatencyRunner:
    """Run latency probes for many profiles with bounded parallelism."""

    def __init__(
        self,
        probe: ProbeFn,
        *,
        max_workers: int = 4,
        dispatch: DispatchFn = _default_dispatch,
    ) -> None:
        self._probe = probe
        self._max_workers = max_workers
        self._dispatch = dispatch
        self._lock = threading.Lock()
        self._busy = False
        self._thread: threading.Thread | None = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def run(
        self,
        profile_ids: Iterable[int],
        *,
        on_result: ResultFn,
        on_done: Callable[[], None],
    ) -> bool:
        """Start probing. Returns False if a run is already in progress."""
        ids = list(profile_ids)
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def _safe_probe(profile_id: int) -> int:
            try:
                return int(self._probe(profile_id))
            except Exception as e:  # noqa: BLE001 - результат всегда доставляется
                logger.exception("Latency probe failed for profile %s: %s", profile_id, e)
                return -1

        def _worker() -> None:
            try:
                with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                    for profile_id, latency in zip(ids, pool.map(_safe_probe, ids)):
                        self._dispatch(on_result, profile_id, latency)
            finally:
                with self._lock:
                    self._busy = False
                self._dispatch(on_done)

        self._thread = threading.Thread(target=_worker, name="latency-runner", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current run finishes (tests only)."""
        if self._thread is not None:
            self._thread.join(timeout)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_logic_latency.py -v`
Expected: 3 passed

**Step 5: Wire runner into MainWindow**

В `src/ui/main_window.py`:
- в `__init__` добавить `self._latency_runner = LatencyRunner(self._run_profile_latency_test)`;
- в `_on_test_delay_clicked` заменить обе ветки (`profile_id` и `group_id`) на один вызов:

```python
        targets = [profile_id] if profile_id is not None else [p.id for p in profiles]
        if not targets:
            return
        for pid in targets:
            self._update_profile_ping_in_ui(pid, -2)
        self._delay_label.set_text(
            "..." if len(targets) == 1 else f"Тестирование {len(targets)} профилей..."
        )

        def on_result(pid: int, latency_ms: int) -> None:
            entry = self._context.profiles.get_profile(pid)
            if entry:
                entry.latency_ms = latency_ms
            self._update_profile_ping_in_ui(pid, latency_ms)
            if len(targets) == 1:
                self._show_delay_result(latency_ms)

        def on_done() -> None:
            self._context.profiles.save()
            if len(targets) > 1:
                self._delay_label.set_text("Готово")

        if not self._latency_runner.run(targets, on_result=on_result, on_done=on_done):
            self._delay_label.set_text("Тест уже выполняется")
```

`profile.latency_ms` и `profiles.save()` теперь меняются только в главном потоке.
Удалить внутренние функции `do_test`, `test_profile`, `test_all_profiles` и импорт `threading`, если он больше не нужен.

**Step 6: Run full suite and lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all passed, no lint errors (существующий `tests/test_ui_app_latency_flow.py` должен пройти без изменений).

**Step 7: Commit**

```bash
git add src/ui/logic tests/test_ui_logic_latency.py src/ui/main_window.py
git commit -m "fix: bound latency probes with LatencyRunner and save profiles on main thread"
```

### ✅ Task 0.2: Сигналы через GLib.unix_signal_add (B3)

**Files:**
- Modify: `src/ui/app.py:100-110`
- Test: `tests/test_ui_app_signals.py`

**Step 1: Write the failing test**

```python
# tests/test_ui_app_signals.py
from __future__ import annotations

import signal
from types import SimpleNamespace

from src.ui import app as app_module


def test_signal_handlers_registered_via_glib(monkeypatch):
    registered: list[tuple[int, int]] = []

    def fake_unix_signal_add(priority, signum, callback, *args):
        registered.append((priority, signum))
        return 42

    monkeypatch.setattr(app_module.GLib, "unix_signal_add", fake_unix_signal_add)
    monkeypatch.setattr(
        app_module.signal, "signal", lambda *a: (_ for _ in ()).throw(AssertionError("signal.signal used"))
    )

    app = app_module.TengaApp.__new__(app_module.TengaApp)
    app._signal_source_ids = []
    app._setup_signal_handlers()

    assert sorted(s for _, s in registered) == sorted([signal.SIGINT, signal.SIGTERM])
    assert app._signal_source_ids == [42, 42]


def test_on_signal_quits_and_returns_source_remove():
    calls: list[str] = []
    app = app_module.TengaApp.__new__(app_module.TengaApp)
    app._lock = SimpleNamespace(release=lambda: calls.append("release"))
    app.quit = lambda: calls.append("quit")

    assert app._on_signal(signal.SIGTERM) is app_module.GLib.SOURCE_REMOVE
    assert calls == ["release", "quit"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_app_signals.py -v`
Expected: FAIL (`signal.signal used` / `_on_signal() takes 3 positional arguments`)

**Step 3: Write minimal implementation**

В `src/ui/app.py` заменить `_setup_signal_handlers` и `_on_signal`:

```python
    def _setup_signal_handlers(self) -> None:
        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK)."""
        self._signal_source_ids = [
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal, signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        ]

    def _on_signal(self, signum: int) -> bool:
        """Signal handler running on the main loop."""
        logger.info("Received signal %s, terminating application", signum)
        if self._lock:
            self._lock.release()
        self.quit()
        return GLib.SOURCE_REMOVE
```

В `__init__` перед вызовом `_setup_signal_handlers()` добавить `self._signal_source_ids: list[int] = []`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_app_signals.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/ui/app.py tests/test_ui_app_signals.py
git commit -m "fix: route SIGINT/SIGTERM through GLib main loop"
```

### ✅ Task 0.3: Единая константа LOCAL_NETWORKS (B5)

**Files:**
- Modify: `src/db/config.py` (рядом с `ROUTING_GROUPS`, строка ~305)
- Modify: `src/ui/app.py:566-575, 588-597`
- Modify: `src/ui/dialogs/profile_vpn_settings.py:621-630`
- Test: `tests/test_db_config_local_networks.py`

**Step 1: Write the failing test**

```python
# tests/test_db_config_local_networks.py
import ipaddress

from src.db.config import LOCAL_NETWORKS


def test_local_networks_are_valid_cidrs_and_unique():
    parsed = [ipaddress.ip_network(n) for n in LOCAL_NETWORKS]
    assert len(parsed) == len(set(parsed))
    assert "127.0.0.0/8" in LOCAL_NETWORKS
    assert "fe80::/10" in LOCAL_NETWORKS
    assert isinstance(LOCAL_NETWORKS, tuple)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_config_local_networks.py -v`
Expected: FAIL with `ImportError: cannot import name 'LOCAL_NETWORKS'`

**Step 3: Write minimal implementation**

В `src/db/config.py` после `DEFAULT_ROUTING_ORDER`:

```python
# Сети, которые никогда не должны уходить в прокси (bypass_local_networks)
LOCAL_NETWORKS: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)
```

В `src/ui/app.py` заменить оба литерала на `local_networks = list(LOCAL_NETWORKS)` (добавить в импорт из `src.db.config`). В `profile_vpn_settings.py:621` аналогично.

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all passed; `grep -rn '"169.254.0.0/16"' src/` находит только `src/db/config.py`.

**Step 5: Commit**

```bash
git add src/db/config.py src/ui/app.py src/ui/dialogs/profile_vpn_settings.py tests/test_db_config_local_networks.py
git commit -m "refactor: share LOCAL_NETWORKS constant between config builder and dialog"
```

### ✅ Task 0.4: Мёртвый код и неиспользуемые импорты (B6)

**Files:**
- Modify: `src/ui/app.py:732-741`
- Modify: `src/ui/main_window.py:3` (`import array`), `:31` (`format_bytes`)
- Modify: `src/ui/dialogs/settings.py:8` (`RoutingMode`)
- Create: `src/ui/logic/formatting.py`
- Test: `tests/test_ui_logic_formatting.py`

**Step 1: Write the failing test**

```python
# tests/test_ui_logic_formatting.py
import pytest

from src.ui.logic.formatting import format_bytes


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"), (5 * 1024**2, "5.0 MB"), (3 * 1024**3, "3.0 GB")],
)
def test_format_bytes(value, expected):
    assert format_bytes(value) == expected
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_logic_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement**

Перенести тело `format_bytes` из `main_window.py:31` в `src/ui/logic/formatting.py` (сверить формат вывода с текущей реализацией и при необходимости поправить ожидания теста под неё — функция пока нигде не используется, поэтому формат допустимо зафиксировать как в тесте). Удалить из `main_window.py` функцию и `import array`. В `app.py:732-741` оставить одно присваивание `outbounds = [outbound, direct_outbound]`. Удалить `RoutingMode` из импорта в `settings.py`.

**Step 4: Run lint and tests**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: no F401/F841, all passed

**Step 5: Commit**

```bash
git add src/ui/app.py src/ui/main_window.py src/ui/dialogs/settings.py src/ui/logic/formatting.py tests/test_ui_logic_formatting.py
git commit -m "refactor: drop dead branches and move format_bytes into ui.logic"
```

### ✅ Task 0.5: Диалоги группы и добавления профиля не закрываются при ошибке (B7)

**Files:**
- Modify: `src/ui/dialogs/edit_group.py:115-137`
- Modify: `src/ui/dialogs/add_profile.py:175-190`
- Test: `tests/test_ui_dialog_validation_loops.py`

**Step 1: Write the failing test** (по образцу `tests/test_ui_subscription_flow.py`)

```python
# tests/test_ui_dialog_validation_loops.py
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from src.ui.dialogs import add_profile, edit_group


class _FakeDialog:
    def __init__(self, *_args, **_kwargs):
        self.run_calls = 0
        self.destroyed = False

    def run(self):
        self.run_calls += 1
        return Gtk.ResponseType.OK

    def destroy(self):
        self.destroyed = True


def test_edit_group_dialog_reruns_until_valid_name(monkeypatch):
    class FakeGroupDialog(_FakeDialog):
        def get_group_name(self):
            return None if self.run_calls == 1 else "Work"

    dialog = FakeGroupDialog()
    monkeypatch.setattr(edit_group, "EditGroupDialog", lambda *a, **k: dialog)

    assert edit_group.show_edit_group_dialog() == "Work"
    assert dialog.run_calls == 2
    assert dialog.destroyed is True


def test_add_profile_dialog_reruns_until_link_parses(monkeypatch):
    class FakeAddDialog(_FakeDialog):
        def get_profile(self):
            return None if self.run_calls == 1 else "bean"

    dialog = FakeAddDialog()
    monkeypatch.setattr(add_profile, "AddProfileDialog", lambda *a, **k: dialog)

    assert add_profile.show_add_profile_dialog() == "bean"
    assert dialog.run_calls == 2
    assert dialog.destroyed is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_dialog_validation_loops.py -v`
Expected: FAIL (`run_calls == 1`, результат `None`)

**Step 3: Implement**

Обе `show_*` функции переписать по образцу `subscription.py:194-216`:

```python
def show_edit_group_dialog(parent=None, group=None) -> str | None:
    dialog = EditGroupDialog(parent, group)
    result = None
    while dialog.run() == Gtk.ResponseType.OK:
        result = dialog.get_group_name()
        if result is not None:
            break
    dialog.destroy()
    return result
```

Аналогично `show_add_profile_dialog` с `get_profile()`. Убедиться, что `get_profile()` в `AddProfileDialog` при ошибке парсинга пишет текст в `_status_label` (проверить `add_profile.py:150-170`; если нет — добавить `self._status_label.set_markup('<span color="red">Не удалось разобрать ссылку</span>')`).

**Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all passed

**Step 5: Commit**

```bash
git add src/ui/dialogs/edit_group.py src/ui/dialogs/add_profile.py tests/test_ui_dialog_validation_loops.py
git commit -m "fix: keep group and add-profile dialogs open after validation errors"
```

### ✅ Task 0.6: Монитор не накапливает потоки (B4)

**Files:**
- Modify: `src/core/monitor.py:38-48, 99-116, 195-233`
- Test: `tests/test_core_monitor.py` (добавить тест)

**Step 1: Write the failing test**

```python
def test_check_skipped_while_previous_check_running(tmp_path, monkeypatch):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 1

    started: list[object] = []

    class FakeThread:
        def __init__(self, target, daemon):
            self._target = target

        def start(self):
            started.append(self._target)

    monkeypatch.setattr("src.core.monitor.threading.Thread", FakeThread)

    assert monitor._check_connections() is True
    assert monitor._check_connections() is True  # второй тик пропускается
    assert len(started) == 1
    assert monitor._check_in_progress is True

    monitor._finish_check()
    assert monitor._check_in_progress is False
    assert monitor._check_connections() is True
    assert len(started) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_monitor.py -k skipped -v`
Expected: FAIL with `AttributeError: _check_in_progress`

**Step 3: Implement**

- В `__init__`: `self._check_in_progress = False`.
- В `_check_connections` перед созданием потока:

```python
        if self._check_in_progress:
            logger.debug("Previous connection check still running, skipping tick")
            return True
        self._check_in_progress = True
```

- `_do_check_async` обернуть в `try/finally`, где `finally` делает `GLib.idle_add(self._finish_check)`.
- Добавить:

```python
    def _finish_check(self) -> bool:
        self._check_in_progress = False
        return False
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_monitor.py -v`
Expected: all passed

**Step 5: Commit**

```bash
git add src/core/monitor.py tests/test_core_monitor.py
git commit -m "fix: skip monitor tick while previous check is still running"
```

### ✅ Task 0.7: Сокет single instance в короткой директории (B20)

**Files:**
- Modify: `src/sys/single_instance.py:25`
- Test: `tests/test_sys_single_instance.py` (добавить тест)

**Step 1: Write the failing test**

```python
def test_socket_path_falls_back_to_runtime_dir_when_too_long(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    long_dir = tmp_path / ("x" * 120)
    long_dir.mkdir()

    instance = SingleInstance(long_dir / "tenga.lock")

    assert instance._socket_file.parent == runtime
    assert len(str(instance._socket_file)) < 108
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sys_single_instance.py -k too_long -v`
Expected: FAIL (`parent == long_dir`)

**Step 3: Implement**

```python
_MAX_UNIX_SOCKET_PATH = 107  # sun_path limit on Linux minus NUL


def _socket_path_for(lock_file: Path) -> Path:
    candidate = lock_file.with_suffix(".sock")
    if len(str(candidate).encode()) <= _MAX_UNIX_SOCKET_PATH:
        return candidate
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    digest = hashlib.sha1(str(lock_file).encode()).hexdigest()[:12]
    return runtime_dir / f"tenga-proxy-{digest}.sock"
```

и в `__init__`: `self._socket_file = _socket_path_for(lock_file)`.

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_single_instance.py -v`
Expected: all passed

**Step 5: Commit**

```bash
git add src/sys/single_instance.py tests/test_sys_single_instance.py
git commit -m "fix: place single-instance socket in runtime dir when config path is too long"
```

### ✅ Task 0.8: Вынести сборку конфигурации xray из app.py

Подготовка к миграции: `app.py` содержит ~700 строк генерации конфигурации xray (`_create_config`, `_create_latency_test_config`, `_reserve_latency_port_pair`, `test_profile_latency`), которые не зависят от GTK и нужны новому `application.py` в неизменном виде.

**Files:**
- Create: `src/core/config_builder.py`
- Modify: `src/ui/app.py` (методы становятся тонкими обёртками или вызовами модуля)
- Modify: `tests/test_ui_app_latency_flow.py` (патчи переключить на новый модуль)
- Test: `tests/test_core_config_builder.py`

**Step 1: Write the failing test**

Тест-характеристика: для VLESS-профиля из `tests/test_fmt_xray_config_valid.py` результат `build_session_config(context, profile)` содержит `inbounds`, `outbounds` с тегами `proxy` и `direct`, а `build_latency_probe_config(context, profile)` возвращает `(config, socks_port)` без TUN-inbound.

**Step 2: Run test to verify it fails** — `ModuleNotFoundError`.

**Step 3: Implement** — чистый перенос кода без изменения поведения: функции модуля принимают `context` и `profile` явно. Методы `TengaApp` вызывают их. `test_profile_latency` переезжает в `src/core/latency_probe.py` рядом с существующей логикой `XrayManager.test_delay_realistic` (см. `tests/test_core_latency_probe.py`).

**Step 4: Run tests** — `uv run pytest -q`, включая `tests/test_ui_app_latency_flow.py` после обновления патчей.

**Step 5: Commit**

```bash
git commit -am "refactor: extract xray config building from TengaApp into core.config_builder"
```

### ✅ Task 0.9: Проверка этапа 0

Run: `python cli.py lint-all && uv run pytest -q`
Expected: 0 ошибок, все тесты проходят.

Ручная проверка (`uv run python gui.py`): тест задержки группы из 100+ профилей не создаёт более 4 процессов xray одновременно (`watch -n1 'pgrep -c xray'`), Ctrl+C в терминале корректно завершает приложение, диалог группы с пустым именем показывает ошибку и остаётся открытым.

Коммитить версию (`python cli.py bump-version 0.12.1`) только по решению владельца.

---

## Этап 1. Оболочка GTK4 + libadwaita

Ветка: `git checkout -b feature/ui-adwaita` от `develop` после этапа 0.
Старый GTK3-код остаётся в `src/ui` до конца этапа 3 и удаляется в этапе 5;
новый живёт рядом и запускается через `gui.py --gtk4` (флаг убирается в этапе 5).

### Task 1.1: Инфраструктура тестов GTK4

**Files:**
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` (маркер `gtk`), `Makefile` (цель `test-gtk`)

Содержимое `conftest.py`: фикстура `gtk_app`, которая проверяет
`Gtk.init_check()` и при отсутствии дисплея делает `pytest.skip`, а также
`pytest.ini` маркер `gtk: требует дисплея (xvfb-run)`.
В `pyproject.toml` добавить `markers = ["gtk: requires a display"]` и по умолчанию
`addopts` дополнить `-m "not gtk"`, чтобы `uv run pytest` оставался быстрым.
`make test-gtk` = `xvfb-run -a uv run pytest -m gtk -p no:cacheprovider`.

**Критерий приёмки:** `uv run pytest -q` не требует дисплея; `make test-gtk`
запускается и сообщает «no tests ran» до появления первых виджетов.

**Commit:** `test: add gtk marker and xvfb test target`

### Task 1.2: TengaApplication (Adw.Application)

**Files:**
- Create: `src/ui/application.py`
- Create: `tests/test_ui_application.py` (маркер `gtk`)
- Modify: `gui.py` (флаг `--gtk4`, проверка версий)

Требования:
- `class TengaApplication(Adw.Application)` с `application_id="ru.tenga.Proxy"`;
- `do_startup`: регистрация действий `connect`, `disconnect`, `toggle-connection`,
  `add-profile`, `add-profile-from-clipboard`, `add-subscription`, `add-group`,
  `refresh-subscriptions`, `settings`, `about`, `shortcuts`, `quit`, `hide-window`,
  и ускорителей из дизайн-документа;
- `do_activate`: создаёт окно один раз, иначе `present()` (заменяет самописный сокет);
- `GLib.unix_signal_add` для SIGINT/SIGTERM;
- `Adw.StyleManager` оставляется в `DEFAULT` (следует системной теме);
- метод `toast(text)` — прокси к `ToastOverlay` окна;
- в `gui.py` перед импортом: проверка `Adw` ≥ 1.5 и понятная ошибка со списком
  пакетов (`gir1.2-gtk-4.0`, `gir1.2-adw-1`).

**Тесты (gtk):** приложение создаётся; все перечисленные действия
зарегистрированы (`app.list_actions()`); повторный `activate` не создаёт второе окно.

**Commit:** `feat: add Adw.Application shell with global actions`

### Task 1.3: MainWindow и StatusCard

**Files:**
- Create: `src/ui/window.py`, `src/ui/widgets/status_card.py`, `src/ui/style.css`
- Create: `tests/test_ui_window.py`, `tests/test_ui_logic_status.py`

Требования к окну: `Adw.ApplicationWindow` → `Adw.ToastOverlay` →
`Adw.ToolbarView` (`Adw.HeaderBar` с `Adw.ViewSwitcher`, меню «☰» и «＋»,
кнопка поиска) → `Adw.ViewStack` с тремя страницами-заглушками.
`Adw.Breakpoint` на `max-width: 550sp` переносит переключатель в
`Adw.ViewSwitcherBar`. Геометрия сохраняется в `close-request` (B12),
восстанавливается в `__init__` через `set_default_size`, без `move()`.

`StatusCard`: `Gtk.Box` с классами `card`, содержит индикатор состояния
(`Gtk.Image` symbolic + CSS-класс `status-*`), заголовок, подзаголовок
(имя профиля), строку метрик (задержка, ↑/↓ трафик, режим) и кнопку действия.
Логика текста и классов выносится в `src/ui/logic/status.py`
(`status_text(state) -> (title, subtitle, css_class, button_label, button_class)`)
и тестируется без GTK.

**Тесты:** `test_ui_logic_status.py` — таблица состояний (отключено, подключение,
подключено с профилем, ошибка). `test_ui_window.py` (gtk) — окно строится,
`ViewStack` содержит три страницы, брейкпоинт добавлен, `close-request`
вызывает сохранение геометрии.

**Commit:** `feat: add main window shell with status card`

### Task 1.4: run_in_background

**Files:**
- Create: `src/ui/logic/async_utils.py`
- Create: `tests/test_ui_logic_async.py`

```python
def run_in_background(fn, on_done=None, on_error=None, *, dispatch=_default_dispatch) -> threading.Thread
```

Выполняет `fn()` в потоке-демоне, результат или исключение доставляет через
`dispatch` (по умолчанию `GLib.idle_add`, всегда возвращающий `SOURCE_REMOVE`).
Тесты подменяют `dispatch` списком, как в Task 0.1.

**Commit:** `feat: add run_in_background helper for GTK-safe threading`

**Критерий приёмки этапа 1:** `uv run python gui.py --gtk4` открывает пустое окно
с header bar, переключателем и статус-карточкой, реагирующей на реальное
состояние подключения; светлая и тёмная системная тема выглядят корректно;
`make test-gtk` зелёный.

---

## Этап 2. Страницы

### Task 2.1: Модель профилей

**Files:**
- Create: `src/ui/models/profile_items.py`, `src/ui/models/filters.py`
- Create: `tests/test_ui_models_filters.py`

`ProfileItem(GObject.Object)` со свойствами `id`, `name`, `protocol`, `server`,
`latency_ms`, `is_selected`, `is_group`, `child_count`. Построение
`Gtk.TreeListModel` из `ProfileStore`: корневой `Gio.ListStore` групп, для
группы — `Gio.ListStore` профилей.

`filters.py` — чистые функции: `matches(item, query)` (имя, тип, сервер, группа),
`sort_key(item, column, descending)`, `visible_groups(store, query)`.
Тесты без GTK на обычных `SimpleNamespace`.

**Commit:** `feat: add profile list model and pure filter helpers`

### Task 2.2: ProfilesPage

**Files:**
- Create: `src/ui/pages/profiles.py`
- Create: `tests/test_ui_page_profiles.py` (gtk)

`Gtk.ColumnView` с колонками Имя (с `Gtk.TreeExpander` и иконкой флага/протокола),
Тип, Сервер, Задержка (цветной класс). `Gtk.SingleSelection` поверх
`Gtk.FilterListModel(Gtk.SortListModel(TreeListModel))`. `Gtk.SearchBar`
привязан к `win.search`. Контекстное меню `Gtk.PopoverMenu` из `Gio.Menu`,
показывается по правой кнопке (`Gtk.GestureClick`), по клавише Menu и Shift+F10
(`Gtk.ShortcutController`). Пустое состояние — `Adw.StatusPage`.
Список `vexpand=True`, ограничений высоты нет (B11).

**Тесты (gtk):** страница строится с 3 группами и 5 профилями; ввод текста в
поиск сокращает число видимых строк; активация строки вызывает `app.connect`;
контекстное меню открывается по Shift+F10.

**Commit:** `feat: add profiles page on Gtk.ColumnView`

### Task 2.3: SubscriptionsPage

**Files:**
- Create: `src/ui/pages/subscriptions.py`
- Create: `tests/test_ui_page_subscriptions.py` (gtk)

`Gtk.ListBox` (`boxed-list`) из `Adw.ActionRow`, суффикс — число профилей и дата,
кнопки Обновить/Редактировать/Удалить. Обновление подписки идёт через
`run_in_background`, во время работы строка показывает `Gtk.Spinner` и
блокирует повторный запуск; результат — `Adw.Toast` («Обновлено: N профилей»
или текст ошибки), после чего `ProfilesPage` перезагружает модель.

**Commit:** `feat: add subscriptions page with async refresh and toasts`

### Task 2.4: MonitoringPage

**Files:**
- Create: `src/ui/pages/monitoring.py`
- Create: `tests/test_ui_page_monitoring.py` (gtk)

`Adw.PreferencesPage`: группы «Соединение», «Маршрутизация активного профиля»,
«Трафик» (использует `format_bytes` из Task 0.4, закрывает B18).
`is_vpn_active()` и чтение файлов маршрутов уходят в `run_in_background` с
кэшированием результата на время между тиками монитора (B10).
Страница добавляется/убирается из `ViewStack` по настройке мониторинга.

**Commit:** `feat: add monitoring page with traffic counters`

### Task 2.5: Подключение действий к состоянию

**Files:**
- Modify: `src/ui/application.py`, `src/ui/window.py`

Действия включаются/выключаются по состоянию (`connect` неактивно без выбранного
профиля, `disconnect` только при активном подключении). Подписка на
`proxy_state` в одном месте — приложение раздаёт обновления окну и трею
(этап 4), окно снимает подписку в `close-request`.

**Критерий приёмки этапа 2:** в новом окне можно выбрать профиль, подключиться,
отключиться, найти профиль поиском, обновить подписку и увидеть тост; ни одна
операция не блокирует UI дольше 100 мс.

**Commit:** `feat: wire window actions to proxy state`

---

## Этап 3. Диалоги

### Task 3.1: Общие подтверждения и тосты

**Files:**
- Create: `src/ui/dialogs/common.py`
- Create: `tests/test_ui_dialogs_common.py` (gtk)

`confirm(parent, heading, body, confirm_label, destructive=True, on_confirm=...)`
поверх `Adw.AlertDialog`; `toast(window, text)`. Заменяет 16 копий
`Gtk.MessageDialog` (B14).

**Commit:** `feat: add shared confirm dialog and toast helpers`

### Task 3.2: AddProfileDialog и SubscriptionDialog

**Files:**
- Create: `src/ui/dialogs/add_profile.py`, `src/ui/dialogs/subscription.py`
- Create: `tests/test_ui_dialogs_add.py` (gtk), `tests/test_ui_logic_validation.py`

`Adw.Dialog` с `Adw.PreferencesGroup` и `Adw.EntryRow`. Валидация вынесена в
`src/ui/logic/validation.py` (`parse_share_link(text)`, `validate_subscription_url(text)`)
и тестируется без GTK. Кнопка подтверждения неактивна, пока ввод невалиден, —
это структурно закрывает B7 в новом UI. Кнопка вставки из буфера использует
`Gdk.Clipboard.read_text_async`.

**Commit:** `feat: add Adw dialogs for profile and subscription creation`

### Task 3.3: ProfileDialog (объединённый)

**Files:**
- Create: `src/ui/dialogs/profile.py`
- Move: логика замены ссылки из старых `edit_profile.py` и `profile_vpn_settings.py`
  в `src/ui/logic/profile_edit.py`
- Modify: `tests/test_ui_profile_edit_link.py` (переписать на новый модуль)

`Adw.PreferencesDialog` с тремя страницами (Профиль / VPN / Маршруты), закрывает
B15. Все вызовы `nmcli`/`ip` — через `run_in_background`; до получения списков
`Adw.ComboRow` показывает «Загрузка…» и неактивен (B10). Сохранение применяет
изменения к `ProfileEntry` и вызывает колбэк перезагрузки конфигурации.

`src/ui/logic/profile_edit.py` содержит чистые функции
`apply_share_link(entry, link) -> tuple[ProfileEntry, str | None]` и
`collect_routing_settings(...)`, покрытые существующими тестами замены ссылки.

**Commit:** `feat: merge profile edit and VPN settings into one Adw dialog`

### Task 3.4: SettingsDialog и AboutDialog

**Files:**
- Create: `src/ui/dialogs/settings.py`
- Modify: `src/ui/application.py` (действие `about` → `Adw.AboutDialog`)

Страницы Основные / Мониторинг / DNS / Логи на `Adw.PreferencesPage` с
`Adw.SwitchRow`, `Adw.SpinRow`, `Adw.ComboRow`, `Adw.EntryRow`. Очистка логов —
`run_in_background` + подтверждение через `confirm()` (B10). Радиокнопки DNS
заменяются `Adw.ComboRow`, пустой обработчик `_on_dns_provider_changed` удаляется.

**Критерий приёмки этапа 3:** все операции старого UI доступны в новом; открытие
диалога профиля с активным NetworkManager не подвешивает окно; тексты кнопок
русские (B13).

**Commit:** `feat: add Adw preferences dialog for app settings`

---

## Этап 4. Трей StatusNotifierItem

### Task 4.1: dbusmenu — дерево меню

**Files:**
- Create: `src/ui/tray/dbusmenu.py`
- Create: `tests/test_ui_tray_dbusmenu.py` (без дисплея)

Структура `MenuItem(id, label, action, enabled=True, visible=True, toggle=None, children=())`
и функции `build_layout(items)` → вложенный вариант формата
`com.canonical.dbusmenu.GetLayout`, `group_properties(items, ids, props)`.
Полностью чистый Python, тестируется сравнением словарей.

**Commit:** `feat: add dbusmenu layout serialization`

### Task 4.2: StatusNotifierItem по D-Bus

**Files:**
- Create: `src/ui/tray/sni.py`
- Create: `tests/test_ui_tray_sni.py` (`Gio.TestDBus`, маркер `gtk` не нужен)

Экспорт интерфейсов `org.kde.StatusNotifierItem` и `com.canonical.dbusmenu` через
`Gio.DBusConnection.register_object` с XML-описанием. Регистрация в
`org.kde.StatusNotifierWatcher`, переподключение через `Gio.bus_watch_name`.
Методы `set_status(state)`, `set_tooltip(text)`, `set_menu(items)` шлют
`NewStatus`/`NewIcon`/`LayoutUpdated`. Если watcher не появился за 5 секунд —
запись в лог уровня INFO и работа без трея.

**Тест:** поднять приватную шину, зарегистрировать фейковый watcher, проверить
что элемент регистрируется, `GetLayout` отдаёт ожидаемое дерево, `Event("clicked")`
вызывает связанное действие.

**Commit:** `feat: implement StatusNotifierItem tray over D-Bus`

### Task 4.3: Иконки и TrayController

**Files:**
- Create: `assets/icons/hicolor/symbolic/apps/tenga-proxy-{disconnected,connected,connecting}-symbolic.svg`
- Create: `src/ui/tray/tray.py`
- Modify: `src/ui/application.py`, `core/scripts/build_appimage.sh`

Три различимые иконки (B17). `TrayController` подписывается на `proxy_state`,
обновляет статус, заголовок и пункт подключения, перестраивает подменю профилей
(не более 20 последних + «Показать все»), пункты вызывают те же `Gio.Action`,
что и окно.

**Критерий приёмки этапа 4:** в GNOME с расширением AppIndicator и в KDE иконка
появляется, меняет вид при подключении, меню работает; без watcher приложение
запускается без ошибок.

**Commit:** `feat: connect tray controller to application actions`

---

## Этап 5. Сборка, документация, завершение

### Task 5.1: Удаление GTK3-кода

**Files:**
- Delete: `src/ui/app.py`, `src/ui/main_window.py`, `src/ui/style.py`, `src/ui/tray.py`,
  старые `src/ui/dialogs/{add_profile,edit_group,edit_profile,settings,subscription,profile_vpn_settings}.py`
- Modify: `gui.py` (убрать флаг `--gtk4`), `src/ui/__init__.py`, `src/sys/single_instance.py`
  (удалить сокет-часть, оставить файловую блокировку)

Прогнать `grep -rn "Gtk, 3.0\|gi.require_version(\"Gtk\", \"3.0\")" src tests` — должно быть пусто.

**Commit:** `refactor!: remove GTK3 UI in favour of GTK4 + libadwaita`

### Task 5.2: Сборка AppImage

**Files:**
- Modify: `core/scripts/build_appimage.sh:130-160`

Проверки зависимостей: `gir1.2-gtk-4.0`, `gir1.2-adw-1` вместо `gir1.2-gtk-3.0`.
Копирование новых иконок в `usr/share/icons/hicolor/symbolic/apps`.
Сборка и запуск AppImage на чистой Ubuntu 24.04 (VM или контейнер с X11).

**Commit:** `build: require GTK4 and libadwaita in AppImage build`

### Task 5.3: Документация

**Files:**
- Modify: `docs/ru/gui.md`, `docs/en/gui.md`, `README.md`, `CLAUDE.md` (раздел GUI Architecture)
- Replace: `assets/main-screen.png` (новый скриншот)

**Commit:** `docs: update GUI documentation for the Adwaita interface`

### Task 5.4: Финальная проверка и слияние

Чек-лист паритета из дизайн-документа (раздел «Критерии готовности»), затем
`superpowers:requesting-code-review`, `python cli.py bump-version 0.13.0`,
слияние `feature/ui-adwaita` → `develop` через PR.

---

## Риски

| Риск | Смягчение |
|------|-----------|
| StatusNotifierItem не заработает в целевом окружении | Реализуется этапом 4 после того, как окно уже функционально; при неудаче приложение остаётся рабочим без трея, решение о доработке принимается отдельно |
| `Gtk.ColumnView` с 600+ строками тормозит | Модель ленивая (`TreeListModel` создаёт дочерние списки по требованию), фильтрация через `Gtk.FilterListModel`; замер на реальной подписке из 600 профилей в конце этапа 2 |
| Регрессии в логике подключения при переносе кода | Task 0.8 выносит генерацию конфигурации до миграции UI и покрывает её тестами |
| libadwaita 1.5 отсутствует в старых дистрибутивах | Явная проверка версии при старте с инструкцией; минимальная платформа зафиксирована в README |
