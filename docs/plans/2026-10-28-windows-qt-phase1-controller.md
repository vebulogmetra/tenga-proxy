# Фаза 1: контроллер приложения без GTK — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Вынести оркестровку приложения из `src/ui/application.py` в GTK-независимый `AppController`, а зависимость монитора от GLib сделать внедряемой, не меняя поведения на Linux.

**Architecture:** `src/core/main_loop.py` даёт протокол `MainLoop` (отложить в главный поток, таймер, отмена) с реализациями `GLibLoop` и тестовой `ImmediateLoop`. `src/ui/controller.py` держит подключение, данные, подписки, замер, failover, обновления и импорт ссылок; с интерфейсом он говорит через протокол `Shell`. `TengaApplication` остаётся `Adw.Application`, реализует `Shell` классом `_GtkShell` и делегирует контроллеру. Публичные методы приложения сохраняются как делегаты: их зовут окно, трей и тесты.

**Tech Stack:** Python 3.11+, PyGObject (только в `application.py` и `GLibLoop`), pytest, ruff.

**Дизайн:** `docs/plans/2026-10-28-windows-qt-frontend-design.md`, раздел «Контроллер».

---

## Правила фазы

- **Критерий приёмки фазы:** `uv run pytest`, `make test-gtk`, `make test-tray`, `python cli.py lint-all` зелёные, **ни одно ожидание в существующих тестах не правится**. Если тест падает, меняется код, а не тест. Исключение — тест, который проверяет сам факт существования приватного члена; таких в наборе нет (см. задачу 0).
- Один логический коммит на задачу, сообщения на русском в стиле репозитория.
- TDD: сначала падающий тест в `tests/test_ui_controller.py` или `tests/test_core_main_loop.py`, потом код.
- `src/ui/controller.py` и `src/core/main_loop.py` не импортируют `gi` на уровне модуля; `GLibLoop` импортирует GLib лениво **внутри каждого метода**: тесты монитора подменяют `gi.repository.GLib` через `sys.modules` и `patch`, и подмена действует только на импорт в момент вызова.
- Не запускать xray с TUN-конфигами на машине разработчика (интерфейс `xray0` занят).
- Перед каждым коммитом: `uv run pytest -q --no-cov -p no:cacheprovider` и `python cli.py lint-all`. `make test-gtk` и `make test-tray` — в задачах 2, 8 и 9 обязательно, в остальных по желанию.

## Что тесты читают у приложения напрямую (нельзя потерять)

Собрано по `tests/test_ui_application.py`, `tests/test_ui_window.py`, `tests/test_core_monitor.py`, `tests/test_ui_application_signals.py`:

| Член | Где | Решение |
|---|---|---|
| `app._window` | чтение виджетов | остаётся в приложении |
| `app._on_dialog_closed`, `app.current_dialog`, `app.present_dialog` | слот диалога | остаётся в приложении |
| `app._signal_source_ids`, `_setup_signal_handlers` | сигналы POSIX | остаётся в приложении |
| `app._default_subscription_updater(group_id, url)` | строка 220 | метод-делегат к `controller.default_subscription_updater` |
| `app._app_update_thread.join(3)` | строка 1117 | свойство-делегат к `controller.app_update_thread` |
| `TengaApplication.resume_monitoring(SimpleNamespace(context=...))` | `test_core_monitor.py` | тело метода — вызов функции модуля `resume_monitoring(self.context)` |
| `monkeypatch.setattr("src.ui.application.app_version", ...)` | строка 1110 | контроллер получает `app_version` как вызываемый объект; приложение передаёт `lambda: app_version()`, который читает глобал модуля `application` в момент вызова |
| `app.last_toast_for_test`, `app.last_notification_for_test` | многие | ставит `_GtkShell` |
| `app.set_*`, `app.wait_*_for_test`, `app.connect_profile` и т. д. | многие | делегаты, список в задаче 8 |

---

### Task 0: Сверка с кодом

**Files:** только чтение.

**Step 1:** Убедиться, что строки, на которые ссылается план, не сдвинулись:

```bash
grep -n "GLib\." src/core/monitor.py
grep -n "def __init__\|def attach_monitor" src/core/monitor.py
grep -n "    def " src/ui/application.py | wc -l
```

Expected: семь мест с `GLib.` в мониторе (два `timeout_add`, два `source_remove`, три `idle_add`); около 95 методов в `application.py`.

**Step 2:** Убедиться, что колбэки `idle_add` монитора возвращают `False`:

```bash
grep -n "def _apply_traffic\|def _finish_check\|def _update_status_from_async" -A30 src/core/monitor.py | grep "return"
```

Expected: только `return False`. Если появился `return True`, оболочка `dispatch` в `GLibLoop` его проглотит, и колбэк перестанет повторяться — тогда такой вызов остаётся на `schedule`, а не на `dispatch`.

**Step 3:** Зафиксировать исходное состояние тестов:

```bash
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -3
make test-gtk 2>&1 | tail -3
make test-tray 2>&1 | tail -3
```

Записать числа прошедших тестов в раздел «Статус» этого плана: в конце фазы их не должно стать меньше.

---

### Task 1: `MainLoop` — главный цикл как зависимость

**Files:**
- Create: `src/core/main_loop.py`
- Test: `tests/test_core_main_loop.py`

**Step 1: Write the failing test**

```python
"""Главный цикл как зависимость: GLib и мгновенная реализация для тестов."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core.main_loop import GLibLoop, ImmediateLoop


def test_immediate_loop_dispatches_right_away():
    loop = ImmediateLoop()
    seen = []

    loop.dispatch(seen.append, 1)

    assert seen == [1]


def test_immediate_loop_keeps_repeating_timers_and_drops_finished_ones():
    loop = ImmediateLoop()
    ticks = []
    loop.schedule(100, lambda: ticks.append("a") or True)
    loop.schedule(200, lambda: ticks.append("b") or False)

    loop.fire()
    loop.fire()

    assert ticks == ["a", "b", "a"]


def test_immediate_loop_cancel_removes_the_timer():
    loop = ImmediateLoop()
    ticks = []
    handle = loop.schedule(100, lambda: ticks.append(1) or True)

    loop.cancel(handle)
    loop.fire()

    assert ticks == []
    assert loop.cancelled == [handle]


def _fake_glib():
    calls = []
    glib = SimpleNamespace(
        SOURCE_REMOVE=False,
        idle_add=lambda fn, *args: calls.append(("idle", fn, args)) or 7,
        timeout_add=lambda ms, fn: calls.append(("timeout", ms, fn)) or 8,
        source_remove=lambda handle: calls.append(("remove", handle)) or True,
    )
    return glib, calls


def test_glib_loop_imports_glib_lazily_and_wraps_dispatch():
    glib, calls = _fake_glib()
    repository = SimpleNamespace(GLib=glib)
    loop = GLibLoop()
    seen = []

    with patch.dict(sys.modules, {"gi.repository": repository, "gi.repository.GLib": glib}):
        loop.dispatch(seen.append, "x")
        kind, once, args = calls[-1]
        # Оболочка возвращает SOURCE_REMOVE, что бы ни вернул колбэк.
        assert kind == "idle" and args == ()
        assert once() is False
        assert seen == ["x"]

        assert loop.schedule(150, lambda: True) == 8
        assert calls[-1] == ("timeout", 150, calls[-1][2])

        loop.cancel(8)
        assert calls[-1] == ("remove", 8)


def test_glib_loop_schedule_passes_the_callback_positionally():
    """Тесты монитора читают `call[0][1]`: порядок аргументов — часть контракта."""
    glib, calls = _fake_glib()
    repository = SimpleNamespace(GLib=glib)

    with patch.dict(sys.modules, {"gi.repository": repository, "gi.repository.GLib": glib}):
        GLibLoop().schedule(10, print)

    assert calls == [("timeout", 10, print)]


@pytest.mark.parametrize("name", ["dispatch", "schedule", "cancel"])
def test_main_loop_protocol_names(name):
    assert hasattr(ImmediateLoop(), name)
    assert hasattr(GLibLoop(), name)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_main_loop.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.core.main_loop'`

**Step 3: Write minimal implementation**

`src/core/main_loop.py`:

```python
"""Главный цикл как зависимость: отложить в главный поток, таймер, отмена.

Монитор и контроллер интерфейса не знают, GLib это или Qt: им передают объект
с тремя методами. `GLibLoop` импортирует GLib лениво и при каждом вызове:
тесты монитора подменяют `gi.repository.GLib` через `sys.modules` и `patch`,
и подмена действует только на импорт в момент вызова. `ImmediateLoop`
выполняет всё сразу и нужен тестам без главного цикла.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

TimerFn = Callable[[], bool]


class MainLoop(Protocol):
    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        """Выполнить `fn(*args)` в главном потоке один раз."""

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        """Вызывать `fn` каждые `interval_ms`, пока она возвращает True."""

    def cancel(self, handle: object) -> None:
        """Снять таймер, выданный `schedule`."""


class GLibLoop:
    """Главный цикл GLib: `idle_add`, `timeout_add`, `source_remove`."""

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        from gi.repository import GLib

        def _once() -> bool:
            fn(*args)
            # Колбэк может вернуть что угодно (например, `save_config` — True);
            # без оболочки GLib повторял бы его как таймер.
            return GLib.SOURCE_REMOVE

        GLib.idle_add(_once)

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        from gi.repository import GLib

        return GLib.timeout_add(interval_ms, fn)

    def cancel(self, handle: object) -> None:
        from gi.repository import GLib

        GLib.source_remove(handle)


class ImmediateLoop:
    """Для тестов: `dispatch` выполняет сразу, таймеры срабатывают по `fire()`."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, TimerFn]] = []
        self.cancelled: list[object] = []

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        fn(*args)

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        handle = (interval_ms, fn)
        self.scheduled.append(handle)
        return handle

    def cancel(self, handle: object) -> None:
        self.cancelled.append(handle)
        if handle in self.scheduled:
            self.scheduled.remove(handle)

    def fire(self) -> None:
        """Сработать всем таймерам по разу; вернувшие True остаются."""
        pending, self.scheduled = self.scheduled, []
        for handle in pending:
            if handle[1]():
                self.scheduled.append(handle)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core_main_loop.py -q --no-cov -p no:cacheprovider`
Expected: PASS, 7 passed

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/core/main_loop.py tests/test_core_main_loop.py
git commit -m "feat(core): MainLoop — главный цикл как внедряемая зависимость"
```

---

### Task 2: Монитор получает `MainLoop`

**Files:**
- Modify: `src/core/monitor.py:45-63` (конструктор), `:86-100` (старт таймеров), `:112-130` (стоп), `:229-231`, `:342-344`, `:418-420` (idle_add), `:503-516` (`attach_monitor`)
- Test: `tests/test_core_monitor.py` (добавить тесты в конец файла, существующие не трогать)

**Step 1: Write the failing test** (в конец `tests/test_core_monitor.py`)

```python
# --- главный цикл как зависимость ---


def test_monitor_uses_the_injected_loop_for_timers(tmp_path):
    from src.core.main_loop import ImmediateLoop
    from src.core.monitor import ConnectionMonitor

    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    loop = ImmediateLoop()
    monitor = ConnectionMonitor(context, loop=loop)
    monitor._check_connections = lambda: True

    monitor.start()
    monitor.stop()

    intervals = sorted(ms for ms, _fn in loop.cancelled)
    assert intervals == sorted(
        [
            context.config.monitoring.check_interval_seconds * 1000,
            max(200, int(context.config.traffic_loop_interval)),
        ]
    )
    assert loop.scheduled == []


def test_attach_monitor_passes_the_loop_through(tmp_path):
    from src.core.main_loop import ImmediateLoop
    from src.core.monitor import attach_monitor

    context = AppContext(config_dir=tmp_path)
    loop = ImmediateLoop()

    monitor = attach_monitor(context, loop=loop)

    assert monitor._loop is loop


def test_monitor_defaults_to_glib_loop(tmp_path):
    from src.core.main_loop import GLibLoop
    from src.core.monitor import ConnectionMonitor

    assert isinstance(ConnectionMonitor(AppContext(config_dir=tmp_path))._loop, GLibLoop)
```

Проверить, что `AppContext` уже импортирован в начале `tests/test_core_monitor.py` (`grep -n "^from src.core.context import" tests/test_core_monitor.py`); если нет — добавить `from src.core.context import AppContext` к импортам файла.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_monitor.py -q --no-cov -p no:cacheprovider -k "injected_loop or passes_the_loop or defaults_to_glib"`
Expected: FAIL, `TypeError: ConnectionMonitor.__init__() got an unexpected keyword argument 'loop'`

**Step 3: Write minimal implementation**

В `src/core/monitor.py`:

1. Импорт после `from src.core.http_probe import measure_latency`:
   ```python
   from src.core.main_loop import GLibLoop, MainLoop
   ```
2. Конструктор:
   ```python
   def __init__(self, context: AppContext, loop: MainLoop | None = None):
       """
       Initialize monitor.

       Args:
           context: Application context
           loop: главный цикл для таймеров и доставки результатов из потоков;
               по умолчанию GLib
       """
       self._context = context
       self._loop: MainLoop = loop if loop is not None else GLibLoop()
       ...остальное без изменений...
   ```
3. В `start()` заменить
   ```python
   from gi.repository import GLib

   self._timer_id = GLib.timeout_add(interval_ms, self._check_connections)
   ```
   на
   ```python
   self._timer_id = self._loop.schedule(interval_ms, self._check_connections)
   ```
   и `self._traffic_timer_id = GLib.timeout_add(traffic_interval_ms, self._tick_traffic)` на `self._traffic_timer_id = self._loop.schedule(traffic_interval_ms, self._tick_traffic)`.
4. В `stop()` оба блока `from gi.repository import GLib` + `GLib.source_remove(...)` заменить на `self._loop.cancel(self._traffic_timer_id)` и `self._loop.cancel(self._timer_id)`.
5. Три `idle_add`:
   - `GLib.idle_add(self._apply_traffic, stats.upload, stats.download)` → `self._loop.dispatch(self._apply_traffic, stats.upload, stats.download)`
   - `GLib.idle_add(self._finish_check, generation)` → `self._loop.dispatch(self._finish_check, generation)`
   - `GLib.idle_add(self._update_status_from_async, previous_status, new_status)` → `self._loop.dispatch(self._update_status_from_async, previous_status, new_status)`
   Удалить сопутствующие `from gi.repository import GLib`.
6. `attach_monitor`:
   ```python
   def attach_monitor(context: AppContext, loop: MainLoop | None = None) -> ConnectionMonitor:
       ...
       monitor = ConnectionMonitor(context, loop=loop)
   ```

После правки: `grep -n "GLib" src/core/monitor.py` должен вернуть только строки документации, если они есть, и ничего исполняемого.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core_monitor.py -q --no-cov -p no:cacheprovider`
Expected: PASS, все тесты монитора, включая старые с подменой `gi.repository` (они подменяют модуль, который `GLibLoop` импортирует при вызове).

Run: `uv run pytest -q --no-cov -p no:cacheprovider && make test-gtk && make test-tray`
Expected: PASS, числа не меньше, чем в задаче 0.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/core/monitor.py tests/test_core_monitor.py
git commit -m "refactor(core): монитор получает главный цикл зависимостью"
```

---

### Task 3: Каркас контроллера — сообщения, данные, настройки, маршрутизация

**Files:**
- Create: `src/ui/controller.py`
- Create: `tests/test_ui_controller.py`

**Step 1: Write the failing test**

`tests/test_ui_controller.py`:

```python
"""AppController: оркестровка без GTK, проверяется с подменной оболочкой."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.core.context import AppContext
from src.core.main_loop import ImmediateLoop
from src.ui.controller import CONFIRM_DELETE, CONFIRM_URL_CHANGE, AppController, resume_monitoring
from src.ui.logic.status import ConnectionState

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


@dataclass
class Confirm:
    kind: str
    heading: str
    body: str
    on_confirm: object
    confirm_label: str | None


@dataclass
class FakeShell:
    """Запоминает всё, что контроллер просит у интерфейса."""

    window: bool = True
    selected: int | None = None
    toasts: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    confirms: list[Confirm] = field(default_factory=list)
    enabled: dict[str, bool] = field(default_factory=dict)
    tray: list[tuple[ConnectionState, str]] = field(default_factory=list)
    forms: list[tuple] = field(default_factory=list)

    def toast(self, text, *, button=None, action=None):
        self.toasts.append((text, button, action))

    def notify(self, text):
        self.notifications.append(text)

    def has_window(self):
        return self.window

    def refresh_status(self):
        self.calls.append(("refresh_status",))

    def refresh_pages(self):
        self.calls.append(("refresh_pages",))

    def show_connecting(self, profile_name):
        self.calls.append(("show_connecting", profile_name))

    def show_error(self, message):
        self.calls.append(("show_error", message))

    def selected_profile_id(self):
        return self.selected

    def sort_by_ping(self):
        self.calls.append(("sort_by_ping",))

    def set_ping_progress(self, progress):
        self.calls.append(("set_ping_progress", progress))

    def update_group_progress(self, group_id):
        self.calls.append(("update_group_progress", group_id))

    def set_tray_state(self, state, profile_name):
        self.tray.append((state, profile_name))

    def set_action_enabled(self, name, enabled):
        self.enabled[name] = enabled

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None):
        self.confirms.append(Confirm(kind, heading, body, on_confirm, confirm_label))

    def open_subscription_form(self, name, url):
        self.forms.append(("subscription", name, url))

    def open_routing_import(self, rows, on_confirm):
        self.forms.append(("routing-import", rows, on_confirm))

    @property
    def last_toast(self) -> str:
        return self.toasts[-1][0] if self.toasts else ""

    def count(self, name: str) -> int:
        return sum(call[0] == name for call in self.calls)


@pytest.fixture
def made(tmp_path):
    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    loop = ImmediateLoop()
    return AppController(context, shell, loop), shell, loop


def add_profile(controller, group_id=None):
    from src.fmt import parse_link

    return controller.add_profile_from_bean(parse_link(LINK), group_id=group_id)


# --- сообщения ---


def test_notify_user_shows_a_toast_and_a_notification(made):
    controller, shell, _ = made

    controller.notify_user("переключаюсь")

    assert shell.last_toast == "переключаюсь"
    assert shell.notifications == ["переключаюсь"]


# --- данные ---


def test_add_profile_persists_refreshes_and_says_so(made):
    controller, shell, _ = made

    entry = add_profile(controller)

    assert controller.context.profiles.get_profile(entry.id) is not None
    assert shell.last_toast == f"Профиль добавлен: {entry.name}"
    assert shell.count("refresh_pages") == 1


def test_delete_missing_profile_only_toasts(made):
    controller, shell, _ = made

    controller.delete_profile(999)

    assert shell.last_toast == "Профиль не найден"
    assert shell.count("refresh_pages") == 0


def test_delete_profile_removes_it(made):
    controller, shell, _ = made
    entry = add_profile(controller)

    controller.delete_profile(entry.id)

    assert controller.context.profiles.get_profile(entry.id) is None
    assert shell.last_toast == f"Профиль удалён: {entry.name}"


def test_groups_are_added_renamed_and_deleted(made):
    controller, shell, _ = made

    group = controller.add_group("Свои")
    assert shell.last_toast == "Группа добавлена: Свои"

    controller.update_group(group.id, name="Чужие", url="https://sub.example/x")
    stored = controller.context.profiles.get_group(group.id)
    assert (stored.name, stored.subscription_url) == ("Чужие", "https://sub.example/x")

    controller.delete_group(group.id)
    assert controller.context.profiles.get_group(group.id) is None
    assert shell.last_toast == "Удалено: Чужие"


def test_update_missing_group_toasts(made):
    controller, shell, _ = made

    assert controller.update_group(42, name="x") is None
    assert shell.last_toast == "Группа не найдена"


def test_save_profiles_refreshes_pages_and_status(made):
    controller, shell, _ = made

    controller.save_profiles()

    assert shell.count("refresh_pages") == 1
    assert shell.count("refresh_status") == 1


def test_failed_persist_is_reported_not_raised(made, monkeypatch):
    controller, shell, _ = made
    monkeypatch.setattr(controller.context, "save_profiles", lambda: False)

    controller.add_group("Свои")

    assert ("Не удалось сохранить профили", None, None) in shell.toasts


# --- настройки и маршрутизация ---


def test_apply_settings_saves_and_refreshes_status(made):
    controller, shell, _ = made

    assert controller.apply_settings() is True
    assert shell.count("refresh_status") == 1


def test_apply_settings_failure_toasts_and_returns_false(made, monkeypatch):
    controller, shell, _ = made
    monkeypatch.setattr(controller.context, "save_config", lambda: False)

    assert controller.apply_settings() is False
    assert shell.last_toast == "Не удалось сохранить настройки"


def test_restore_routing_action_follows_the_backup(made):
    controller, shell, _ = made

    controller.sync_restore_routing()
    assert shell.enabled["restore-routing"] is False

    controller.context.config.routing_backup = {"direct_list": []}
    controller.sync_restore_routing()
    assert shell.enabled["restore-routing"] is True


def test_restore_routing_without_backup_is_silent(made):
    controller, shell, _ = made

    controller.restore_routing()

    assert shell.toasts == []


# --- наблюдение ---


def test_resume_monitoring_starts_a_running_proxy(tmp_path):
    from unittest.mock import MagicMock

    context = AppContext(config_dir=tmp_path)
    monitor = MagicMock()
    context.set_monitor(monitor)
    context.proxy_state.is_running = True

    resume_monitoring(context)

    monitor.start.assert_called_once()


def test_shutdown_stops_the_connection_service(made):
    controller, _shell, _ = made
    stopped = []
    controller.set_connection_service(
        type("S", (), {"shutdown": lambda self, thread: stopped.append(thread)})()
    )

    controller.shutdown()

    assert stopped == [None]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ui.controller'`

**Step 3: Write minimal implementation**

`src/ui/controller.py` (полный файл на этой задаче; следующие задачи добавляют методы в отмеченные секции):

```python
"""Оркестровка приложения без GTK.

`AppController` держит всё, что не является виджетом: подключение, данные,
подписки, замер задержки, failover, проверку обновлений, импорт ссылок.
С интерфейсом он говорит через `Shell`, с главным потоком — через `MainLoop`,
поэтому один контроллер обслуживает GTK на Linux и Qt на Windows
(docs/plans/2026-10-28-windows-qt-frontend-design.md).

Поведение перенесено из `TengaApplication` один в один: тексты сообщений,
порядок обновления окна и проверки занятости — часть контракта, который
закрепляют GTK-тесты.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from src.core.core_update import is_check_due, refresh_known_releases
from src.core.failover import FailoverController
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner, PingProgress, make_batch_probe
from src.ui.logic.status import ConnectionState
from src.ui.logic.subscriptions_view import describe_update_error, describe_url_change
from src.ui.logic.version import app_version

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.core.main_loop import MainLoop

logger = logging.getLogger("tenga.ui.controller")

# Шаг склейки перерисовок на время замера задержки.
LATENCY_REFRESH_INTERVAL_MS = 150

# Виды подтверждений: оболочка выбирает по ним кнопки и их внешний вид.
CONFIRM_DELETE = "delete"
CONFIRM_URL_CHANGE = "url-change"


class Shell(Protocol):
    """Что контроллеру нужно от интерфейса. Реализуют GTK- и Qt-оболочки.

    Методы, зависящие от окна, при закрытом окне ничего не делают — это
    забота реализации, контроллер их зовёт безусловно.
    """

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None: ...

    def notify(self, text: str) -> None:
        """Системное уведомление: видно и при свёрнутом окне."""

    def has_window(self) -> bool: ...

    def refresh_status(self) -> None: ...

    def refresh_pages(self) -> None: ...

    def show_connecting(self, profile_name: str) -> None: ...

    def show_error(self, message: str) -> None: ...

    def selected_profile_id(self) -> int | None: ...

    def sort_by_ping(self) -> None: ...

    def set_ping_progress(self, progress: PingProgress | None) -> None: ...

    def update_group_progress(self, group_id: int) -> None: ...

    def set_tray_state(self, state: ConnectionState, profile_name: str) -> None: ...

    def set_action_enabled(self, name: str, enabled: bool) -> None: ...

    def confirm(
        self,
        kind: str,
        heading: str,
        body: str,
        on_confirm: Callable[[], None],
        *,
        confirm_label: str | None = None,
    ) -> None: ...

    def open_subscription_form(self, name: str, url: str) -> None: ...

    def open_routing_import(self, rows: list, on_confirm: Callable[[], None]) -> None: ...


def resume_monitoring(context: Any) -> None:
    """Start watching a proxy that is already running.

    Наблюдение запускает подключение, но приложение может открыться при
    уже поднятом прокси — тогда проверки не шли бы вовсе, и страница
    мониторинга показывала бы «Недоступен» при работающем соединении.
    """
    monitor = context.monitor
    if monitor is None or not context.proxy_state.is_running:
        return
    monitor.start()


class AppController:
    """Оркестровка приложения; окно, трей и диалоги — за `Shell`."""

    def __init__(
        self,
        context: AppContext,
        shell: Shell,
        loop: MainLoop,
        *,
        network_available: Callable[[], bool] = lambda: True,
        app_version: Callable[[], str] = app_version,
    ) -> None:
        self.context = context
        self._shell = shell
        self._loop = loop
        self._network_available = network_available
        # Вызываемый объект, а не строка: GTK-тесты подменяют `app_version`
        # в модуле приложения, и подмена должна действовать здесь.
        self._app_version = app_version

        # Потоки и раннер публичные: приложение ждёт их в тестовых помощниках.
        self.latency_runner: LatencyRunner | None = None
        self._latency_probe: Callable[[int], int] | None = None
        self._latency_refresh_handle: object | None = None
        self._ping_progress: PingProgress | None = None
        self._subscription_updater: Callable[[int, str], int] | None = None
        self.subscriptions_thread = None
        self._subscription_busy = False
        # Предложения сменить адрес подписки: копятся в фоновом потоке,
        # показываются в главном, по одному и только с подтверждением.
        self._url_proposals: list = []
        self._profile_activation_handler: Callable[[int], None] | None = None
        self._connection_service = None
        self.connection_thread = None
        self._failover: FailoverController | None = None
        self._release_fetcher: Callable[[], object] | None = None
        self.core_update_thread = None
        self.app_update_thread = None
        self._app_release_fetcher = None

    # --- сообщения ---

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._shell.toast(text, button=button, action=action)

    def notify_user(self, text: str) -> None:
        """Tell the user something they must not miss.

        Тост виден только в открытом окне, а приложение обычно свёрнуто в
        трей — поэтому сообщение дублируется уведомлением рабочего стола.
        """
        self._shell.toast(text)
        self._shell.notify(text)

    # --- жизненный цикл ---

    def resume_monitoring(self) -> None:
        resume_monitoring(self.context)

    def shutdown(self) -> None:
        """Погасить ядро: вызывается до снятия блокировки экземпляра."""
        if self._connection_service is not None:
            self._connection_service.shutdown(self.connection_thread)

    # --- данные ---

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        """Store a parsed profile and persist it."""
        entry = self.context.profiles.add_profile(bean, group_id=group_id)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Профиль добавлен: {entry.name}")
        return entry

    def delete_profile(self, profile_id: int) -> None:
        """Remove one profile."""
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        name = profile.name
        self.context.profiles.remove_profile(profile_id)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Профиль удалён: {name}")

    def add_group(self, name: str):
        """Create a plain group."""
        group = self.context.profiles.add_group(name)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Группа добавлена: {name}")
        return group

    def update_group(self, group_id: int, *, name: str, url: str | None = None):
        """Rename a group and optionally change its subscription address."""
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return None

        group.name = name
        if url is not None:
            group.subscription_url = url
        self._save_profiles()
        self._shell.refresh_pages()
        return group

    def delete_group(self, group_id: int) -> None:
        """Remove a group together with its profiles."""
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return

        name = group.name
        self.context.profiles.remove_group(group_id)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Удалено: {name}")

    def save_profiles(self) -> None:
        """Persist the profile store after an external edit."""
        self._save_profiles()
        self._shell.refresh_pages()
        self._shell.refresh_status()

    def _save_profiles(self) -> None:
        try:
            if not self.context.save_profiles():
                raise OSError("Запись профилей не выполнена")
        except Exception as e:
            logger.warning("Could not persist profiles: %s", e)
            self.toast("Не удалось сохранить профили")

    # --- настройки и маршрутизация ---

    def apply_settings(self) -> bool:
        """Persist settings; runtime changes await an explicit reconnect."""
        try:
            if not self.context.save_config():
                raise OSError("Запись настроек не выполнена")
        except Exception as error:
            logger.warning("Could not persist settings: %s", error)
            self.toast("Не удалось сохранить настройки")
            return False
        monitor = self.context.monitor
        if monitor is not None and self.context.proxy_state.is_running:
            monitor.stop()
            monitor.start()
        self._shell.refresh_status()
        return True

    def apply_routing_import(self, routing) -> None:
        from src.ui.logic.routing_import import apply_import

        apply_import(self.context.config, routing, self.context.config_dir)
        if self.apply_settings():
            self.sync_restore_routing()
            self.toast(
                "Маршрутизация импортирована", button="Вернуть", action="app.restore-routing"
            )

    def restore_routing(self) -> None:
        """Вернуть общую маршрутизацию до последнего импорта ссылкой."""
        from src.ui.logic.routing_import import restore_backup

        if not restore_backup(self.context.config):
            return
        if self.apply_settings():
            self.toast("Маршрутизация до импорта возвращена")
        self.sync_restore_routing()

    def sync_restore_routing(self) -> None:
        self._shell.set_action_enabled(
            "restore-routing", self.context.config.routing_backup is not None
        )

    # --- подключение (задача 4) ---

    def set_connection_service(self, service) -> None:
        """Install the object starting and stopping the proxy."""
        self._connection_service = service

    # --- подписки (задача 5) ---

    # --- замер задержки (задача 6) ---

    # --- обновления и ссылки (задача 7) ---
```

Импорты `time`, `is_check_due`, `refresh_known_releases`, `FailoverController`, `run_in_background`, `LatencyRunner`, `make_batch_probe`, `describe_update_error`, `describe_url_change` на этой задаче ещё не используются; ruff `F401` в проекте отключён, оставить их — следующие задачи их задействуют.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: PASS, 15 passed

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): AppController — оркестровка без GTK: данные, настройки, маршрутизация"
```

---

### Task 4: Контроллер — подключение и failover

**Files:**
- Modify: `src/ui/controller.py` (секция «подключение»)
- Test: `tests/test_ui_controller.py`

**Step 1: Write the failing test** (добавить в конец файла)

```python
# --- подключение ---


class FakeService:
    def __init__(self, calls, *, ok=True, error=""):
        from src.core.connection import ConnectionResult

        self._calls = calls
        self._result = ConnectionResult(ok, error)

    def connect(self, profile_id):
        self._calls.append(("connect", profile_id))
        return self._result

    def disconnect(self):
        self._calls.append(("disconnect",))
        return self._result

    def shutdown(self, thread):
        self._calls.append(("shutdown",))


def _wait(controller):
    if controller.connection_thread is not None:
        controller.connection_thread.join(5)


def test_connect_profile_runs_the_service_and_marks_the_profile_used(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))

    controller.connect_profile(entry.id)
    _wait(controller)

    assert calls == [("connect", entry.id)]
    assert ("show_connecting", entry.name) in shell.calls
    assert shell.tray[0] == (ConnectionState.CONNECTING, entry.name)
    assert shell.last_toast == f"Подключено: {entry.name}"
    assert controller.context.profiles.last_used_profile().id == entry.id
    assert shell.count("refresh_status") >= 1 and shell.count("refresh_pages") >= 1


def test_failed_connection_shows_the_error_everywhere(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.set_connection_service(FakeService([], ok=False, error="нет ядра"))

    controller.connect_profile(entry.id)
    _wait(controller)

    assert shell.last_toast == "Не удалось подключиться: нет ядра"
    assert ("show_error", "нет ядра") in shell.calls
    assert shell.tray[-1] == (ConnectionState.ERROR, "")


def test_connect_unknown_profile_only_toasts(made):
    controller, shell, _ = made

    controller.connect_profile(123)

    assert shell.last_toast == "Профиль не найден"
    assert controller.connection_thread is None


def test_connect_selected_falls_back_to_the_last_used_profile(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.context.profiles.mark_used(entry.id)
    calls = []
    controller.set_connection_service(FakeService(calls))
    shell.selected = None

    controller.connect_selected()
    _wait(controller)

    assert calls == [("connect", entry.id)]


def test_connect_selected_without_any_profile_asks_to_pick_one(made):
    controller, shell, _ = made

    controller.connect_selected()

    assert shell.last_toast == "Выберите профиль в списке"


def test_toggle_disconnects_a_running_proxy(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))
    controller.context.proxy_state.set_running(entry.id)

    controller.toggle_connection()
    _wait(controller)

    assert calls == [("disconnect",)]
    assert shell.last_toast == "Отключено"


def test_select_profile_prefers_the_installed_handler(made):
    controller, _shell, _ = made
    seen = []
    controller.set_profile_activation_handler(seen.append)

    controller.select_profile(5)

    assert seen == [5]


def test_reconnect_current_restarts_the_running_profile(made):
    controller, _shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))
    controller.context.proxy_state.set_running(entry.id)

    controller.reconnect_current()
    _wait(controller)

    assert calls == [("connect", entry.id)]


def test_watch_monitor_hands_failover_to_the_monitor(made):
    from unittest.mock import MagicMock

    controller, _shell, _ = made
    monitor = MagicMock()
    controller.context.set_monitor(monitor)

    controller.watch_monitor()

    monitor.set_on_status_changed.assert_called_once()
    assert controller._failover is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider -k "connect or toggle or select_profile or reconnect or watch_monitor"`
Expected: FAIL, `AttributeError: 'AppController' object has no attribute 'connect_profile'`

**Step 3: Write minimal implementation**

В секцию «подключение» `src/ui/controller.py` после `set_connection_service`:

```python
    def _ensure_connection_service(self):
        if self._connection_service is None:
            from src.core.connection import ConnectionService

            self._connection_service = ConnectionService(self.context)
        return self._connection_service

    def connection_busy(self) -> bool:
        return self.connection_thread is not None and self.connection_thread.is_alive()

    def connect_profile(self, profile_id: int) -> None:
        """Start the proxy for one profile in the background."""
        if self.latency_runner is not None and self.latency_runner.is_busy:
            self.toast("Дождитесь завершения проверки задержки")
            return
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        if self.connection_busy():
            # Два одновременных запуска оставили бы висящий процесс xray.
            self.toast("Подключение уже выполняется")
            return

        self._shell.show_connecting(profile.name)
        # Промежуточное состояние живёт только в UI: в proxy_state его нет,
        # и сам по себе трей о нём не узнает.
        self._shell.set_tray_state(ConnectionState.CONNECTING, profile.name)

        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            lambda: service.connect(profile_id),
            on_done=lambda result: self._on_connection_done(result, profile_id, profile.name),
            on_error=self._on_connection_failed,
            dispatch=self._loop.dispatch,
            name="tenga-connect",
        )

    def disconnect_proxy(self) -> None:
        """Stop the proxy in the background."""
        if self.connection_busy():
            self.toast("Подключение уже выполняется")
            return

        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            service.disconnect,
            on_done=lambda result: self._on_disconnection_done(result),
            on_error=self._on_connection_failed,
            dispatch=self._loop.dispatch,
            name="tenga-disconnect",
        )

    def connect_selected(self) -> None:
        profile_id = self._shell.selected_profile_id()
        if profile_id is None:
            # Трей и кнопка в окне без выделения подключают последний профиль.
            last = self.context.profiles.last_used_profile()
            profile_id = None if last is None else last.id
        if profile_id is None:
            self.toast("Выберите профиль в списке")
            return
        self.connect_profile(profile_id)

    def toggle_connection(self) -> None:
        if self.context.proxy_state.is_running:
            self.disconnect_proxy()
            return
        self.connect_selected()

    def reconnect_current(self) -> None:
        state = self.context.proxy_state
        if state.is_running:
            self.connect_profile(state.started_profile_id)

    def set_profile_activation_handler(self, handler: Callable[[int], None]) -> None:
        """Install what happens when a profile row is activated."""
        self._profile_activation_handler = handler

    def select_profile(self, profile_id: int) -> None:
        """Connect to a profile activated on the profiles page."""
        if self._profile_activation_handler is not None:
            self._profile_activation_handler(profile_id)
            return
        self.connect_profile(profile_id)

    def _on_connection_done(self, result, profile_id: int, profile_name: str) -> None:
        if result.ok:
            self.context.profiles.mark_used(profile_id)
            self._save_profiles()
            self.toast(f"Подключено: {profile_name}")
        else:
            self.toast(f"Не удалось подключиться: {result.error}")
            self._shell.show_error(result.error)
            self._shell.set_tray_state(ConnectionState.ERROR, "")

        self._refresh_window()

    def _on_disconnection_done(self, result) -> None:
        if result.ok:
            self.toast("Отключено")
        else:
            self.toast(f"Не удалось отключиться: {result.error}")
        self._refresh_window()

    def _on_connection_failed(self, error: BaseException) -> None:
        self.toast(f"Ошибка подключения: {error}")
        self._shell.show_error(str(error))
        self._shell.set_tray_state(ConnectionState.ERROR, "")
        self._refresh_window()

    def _refresh_window(self) -> None:
        self._shell.refresh_status()
        self._shell.refresh_pages()

    # --- failover ---

    def watch_monitor(self) -> None:
        """Hand the monitor's verdicts to the failover controller.

        Контроллер сам смотрит в настройки и при выключенном автопереключении
        ничего не делает, поэтому подписка ставится безусловно.
        """
        monitor = self.context.monitor
        if monitor is None:
            return

        self._failover = FailoverController(
            self.context,
            switch_to=self.connect_profile,
            notify=self.notify_user,
            network_available=self._network_available,
        )
        monitor.set_on_status_changed(self._failover.handle_status)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: PASS

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): AppController — подключение, отключение, failover"
```

---

### Task 5: Контроллер — подписки и смена адреса

**Files:**
- Modify: `src/ui/controller.py` (секция «подписки»)
- Test: `tests/test_ui_controller.py`

**Step 1: Write the failing test** (добавить в конец файла)

```python
# --- подписки ---


def _wait_subscriptions(controller):
    if controller.subscriptions_thread is not None:
        controller.subscriptions_thread.join(5)


def test_add_subscription_creates_the_group_and_updates_it(made):
    controller, shell, _ = made
    updated = []
    controller.set_subscription_updater(lambda gid, url: updated.append((gid, url)) or 3)

    group = controller.add_subscription("Demo", "https://sub.example/list")
    _wait_subscriptions(controller)

    assert group.is_subscription and group.subscription_url == "https://sub.example/list"
    assert updated == [(group.id, "https://sub.example/list")]
    assert shell.last_toast == "Обновлено профилей: 3"


def test_update_subscription_without_url_toasts(made):
    controller, shell, _ = made
    group = controller.add_group("Обычная")

    controller.update_subscription(group.id)

    assert shell.last_toast == "У подписки нет адреса"
    assert controller.subscriptions_thread is None


def test_failed_update_reports_the_reason(made):
    controller, shell, _ = made

    def failing(_gid, _url):
        raise RuntimeError("boom")

    controller.set_subscription_updater(failing)
    controller.add_subscription("Demo", "https://sub.example/list")
    _wait_subscriptions(controller)

    assert shell.last_toast.startswith("Не удалось обновить подписки: ")
    assert controller._subscription_busy is False


def test_failed_update_offers_the_providers_fallback_url(made):
    controller, shell, _ = made
    group = controller.add_group("Demo")
    group.subscription_url = "https://sub.example/list"
    group.is_subscription = True
    group.sub_fallback_url = "https://backup.example/sub"

    def failing(_gid, _url):
        raise RuntimeError("boom")

    controller.set_subscription_updater(failing)
    controller.update_subscription(group.id)
    _wait_subscriptions(controller)

    assert shell.confirms[-1].kind == CONFIRM_URL_CHANGE
    assert "https://backup.example/sub" in shell.confirms[-1].body


def test_confirmed_url_change_switches_the_group_and_refreshes(made):
    controller, shell, _ = made
    group = controller.add_group("Demo")
    group.subscription_url = "https://sub.example/list"
    group.is_subscription = True
    group.sub_fallback_url = "https://backup.example/sub"
    seen = []

    def updater(_gid, url):
        seen.append(url)
        if url.startswith("https://sub."):
            raise RuntimeError("boom")
        return 1

    controller.set_subscription_updater(updater)
    controller.update_subscription(group.id)
    _wait_subscriptions(controller)
    shell.confirms[-1].on_confirm()
    _wait_subscriptions(controller)

    assert controller.context.profiles.get_group(group.id).subscription_url == (
        "https://backup.example/sub"
    )
    assert seen == ["https://sub.example/list", "https://backup.example/sub"]


def test_refresh_subscriptions_without_any_toasts(made):
    controller, shell, _ = made

    controller.refresh_subscriptions()

    assert shell.last_toast == "Подписок нет"


def test_refresh_subscriptions_sums_the_groups(made):
    controller, shell, _ = made
    controller.set_subscription_updater(lambda _gid, _url: 2)
    for name in ("A", "B"):
        group = controller.add_group(name)
        group.is_subscription = True
        group.subscription_url = f"https://{name}.example/sub"

    controller.refresh_subscriptions()
    _wait_subscriptions(controller)

    assert shell.last_toast == "Обновлено профилей: 4"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider -k "subscription"`
Expected: FAIL, `AttributeError: ... 'set_subscription_updater'`

**Step 3: Write minimal implementation**

В секцию «подписки»:

```python
    def set_subscription_updater(self, updater: Callable[[int, str], int]) -> None:
        """Install the function refreshing one subscription group."""
        self._subscription_updater = updater

    def add_subscription(self, name: str, url: str):
        """Create a subscription group and fetch it right away."""
        try:
            group = self.context.profiles.find_subscription_group(
                url, exceptions=self.context.config.sub_source_exceptions
            )
        except RuntimeError as error:
            self.toast(str(error))
            return None
        if group is not None:
            self.context.profiles.current_group_id = group.id
            self._shell.refresh_pages()
            self.update_subscription(group.id)
            return group
        group = self.context.profiles.add_group(name, is_subscription=True)
        group.subscription_url = url
        self._save_profiles()
        self._shell.refresh_pages()
        self.update_subscription(group.id)
        return group

    def update_subscription(self, group_id: int) -> None:
        """Refresh one subscription group in the background."""
        if self._subscription_busy or (
            self.latency_runner is not None and self.latency_runner.is_busy
        ):
            self.toast("Обновление подписок или проверка задержки уже выполняется")
            return
        group = self.context.profiles.get_group(group_id)
        if group is None or not group.subscription_url:
            self.toast("У подписки нет адреса")
            return

        updater = self._subscription_updater or self.default_subscription_updater
        url = group.subscription_url

        def work() -> int:
            try:
                return updater(group_id, url)
            except Exception:
                self._propose_fallback_url(group_id, url)
                raise

        self._subscription_busy = True
        self.toast(f"Обновляю: {group.name}")
        self.subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            dispatch=self._loop.dispatch,
            name="tenga-subscription",
        )

    def default_subscription_updater(self, group_id: int, url: str) -> int:
        from src.sub.route import local_proxy_url
        from src.sub.updater import SubscriptionUpdater
        from src.sub.url_change import REASON_NEW_URL, propose_url_change

        context = self.context
        updater = SubscriptionUpdater(
            config=context.config,
            profiles=context.profiles,
            proxy_url=lambda: local_proxy_url(context.config, context.proxy_state),
        )
        beans = updater.update(url, group_id)

        proposal = propose_url_change(group_id, url, updater.new_url, REASON_NEW_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)
        return len(beans)

    def _propose_fallback_url(self, group_id: int, url: str) -> None:
        """Queue the provider's fallback address after a failed update."""
        from src.sub.url_change import REASON_FALLBACK_URL, propose_url_change

        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        proposal = propose_url_change(group_id, url, group.sub_fallback_url, REASON_FALLBACK_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)

    def _offer_url_change(self) -> None:
        """Ask about one queued address change; the rest come back with the next update."""
        if not self._url_proposals:
            return
        proposal = self._url_proposals[0]
        self._url_proposals.clear()

        group = self.context.profiles.get_group(proposal.group_id)
        if group is None or not self._shell.has_window():
            return

        heading, body = describe_url_change(group.name, group.subscription_url, proposal)
        self._shell.confirm(
            CONFIRM_URL_CHANGE, heading, body, lambda: self._apply_url_change(proposal)
        )

    def _apply_url_change(self, proposal) -> None:
        """Switch the subscription to the confirmed address and refresh it."""
        group = self.context.profiles.get_group(proposal.group_id)
        if group is None:
            return
        try:
            collision = self.context.profiles.find_subscription_group(
                proposal.new_url, exceptions=self.context.config.sub_source_exceptions
            )
        except RuntimeError as error:
            self.toast(str(error))
            return
        if collision is not None and collision.id != group.id:
            self.toast("Этот адрес уже используется другой подпиской")
            return
        self.update_group(proposal.group_id, name=group.name, url=proposal.new_url)
        self.update_subscription(proposal.group_id)

    def refresh_subscriptions(self) -> None:
        if self._subscription_busy or (
            self.latency_runner is not None and self.latency_runner.is_busy
        ):
            self.toast("Обновление подписок или проверка задержки уже выполняется")
            return
        groups = [
            group
            for group in self.context.profiles.groups.values()
            if group.is_subscription and group.subscription_url
        ]
        if not groups:
            self.toast("Подписок нет")
            return

        updater = self._subscription_updater or self.default_subscription_updater
        targets = [(group.id, group.subscription_url) for group in groups]

        def work() -> int:
            total = 0
            for group_id, url in targets:
                try:
                    total += updater(group_id, url)
                except Exception as e:
                    logger.warning("Subscription %s failed: %s", group_id, describe_update_error(e))
                    self._propose_fallback_url(group_id, url)
            return total

        self._subscription_busy = True
        self.toast(f"Обновляю подписки: {len(targets)}")
        self.subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            dispatch=self._loop.dispatch,
            name="tenga-subscriptions",
        )

    def _on_subscriptions_updated(self, total: int) -> None:
        self._subscription_busy = False
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist updated subscriptions: %s", e)

        self._shell.refresh_pages()
        self.toast(f"Обновлено профилей: {total}")
        self._offer_url_change()

    def _on_subscriptions_failed(self, error: BaseException) -> None:
        self._subscription_busy = False
        sent = self.context.config.sub_send_device_info
        reason = describe_update_error(error, device_info_sent=sent)
        self.toast(f"Не удалось обновить подписки: {reason}")
        self._offer_url_change()
```

Если тест `test_failed_update_offers_the_providers_fallback_url` падает из-за того, что `propose_url_change` отвергает адрес (например, требует совпадения хоста или проверку исключений), посмотреть `src/sub/url_change.py` и подобрать адрес, который он принимает; GTK-тест `tests/test_ui_application.py` около строки 300 использует `https://backup.example/sub` — ориентироваться на него.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: PASS

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): AppController — обновление подписок и смена адреса"
```

---

### Task 6: Контроллер — замер задержки

**Files:**
- Modify: `src/ui/controller.py` (секция «замер задержки»)
- Test: `tests/test_ui_controller.py`

**Step 1: Write the failing test** (добавить в конец файла)

```python
# --- замер задержки ---


def _wait_latency(controller):
    if controller.latency_runner is not None:
        controller.latency_runner.wait(5)


def test_test_latency_probes_every_profile_and_stores_the_result(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    probed = []
    controller.set_latency_probe(lambda pid: probed.append(pid) or 55)

    controller.test_latency()
    _wait_latency(controller)

    assert probed == [entry.id]
    assert controller.context.profiles.get_profile(entry.id).latency_ms == 55
    assert shell.last_toast == "Проверка задержки завершена"
    assert ("set_ping_progress", None) in shell.calls


def test_test_latency_without_profiles_toasts(made):
    controller, shell, _ = made
    controller.set_latency_probe(lambda _pid: 1)

    controller.test_latency()

    assert shell.last_toast == "Нет профилей для проверки"


def test_probe_is_refused_while_tun_is_active(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.set_latency_probe(lambda _pid: 1)
    controller.context.proxy_state.set_running(entry.id, mode="tun")

    controller.test_latency_for(entry.id)

    assert shell.last_toast.startswith("Замер при активном TUN недоступен")


def test_group_run_sorts_by_ping_and_coalesces_redraws(made):
    controller, shell, loop = made
    group = controller.add_group("G")
    first = add_profile(controller, group_id=group.id)
    second = add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda pid: 10 if pid == first.id else 20)

    controller.test_latency_for_group(group.id)
    _wait_latency(controller)

    assert ("sort_by_ping",) in shell.calls
    assert controller.context.profiles.get_profile(second.id).latency_ms == 20
    # Отложенная перерисовка снята итоговой: таймер отменён, не сработал.
    assert loop.scheduled == [] and len(loop.cancelled) >= 1


def test_keep_working_asks_before_removing_dead_profiles(made):
    controller, shell, _ = made
    group = controller.add_group("G")
    alive = add_profile(controller, group_id=group.id)
    dead = add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda pid: 30 if pid == alive.id else -1)

    controller.keep_working_profiles(group.id)
    _wait_latency(controller)

    confirm = shell.confirms[-1]
    assert confirm.kind == CONFIRM_DELETE and confirm.confirm_label == "Оставить рабочие"
    confirm.on_confirm()
    assert controller.context.profiles.get_profile(dead.id) is None
    assert controller.context.profiles.get_profile(alive.id) is not None


def test_keep_working_is_cancelled_without_network(tmp_path):
    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    controller = AppController(context, shell, ImmediateLoop(), network_available=lambda: False)
    group = controller.add_group("G")
    add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda _pid: -1)

    controller.keep_working_profiles(group.id)
    _wait_latency(controller)

    assert shell.confirms == []
    assert shell.last_toast.startswith("Фильтрация отменена")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider -k "latency or probe or keep_working"`
Expected: FAIL, `AttributeError: ... 'set_latency_probe'`

**Step 3: Write minimal implementation**

В секцию «замер задержки»:

```python
    def set_latency_probe(self, probe: Callable[[int], int]) -> None:
        """Install the function measuring one profile's latency.

        Проба передаётся снаружи: она живёт на уровне ядра и требует запуска
        временного xray, а окно не должно знать об этом.
        """
        self._latency_probe = probe
        self.latency_runner = LatencyRunner(probe, dispatch=self._loop.dispatch)

    def _ensure_latency_runner(self) -> LatencyRunner:
        if self.latency_runner is None:
            if self._latency_probe is not None:
                self.latency_runner = LatencyRunner(
                    self._latency_probe, dispatch=self._loop.dispatch
                )
            else:
                # Весь набор меряет один временный процесс ядра.
                self.latency_runner = LatencyRunner(
                    batch_probe=make_batch_probe(self.context), dispatch=self._loop.dispatch
                )
        return self.latency_runner

    def _can_probe(self) -> bool:
        from src.db.config import ProxyMode

        state = self.context.proxy_state
        if state.is_running and state.started_mode == ProxyMode.TUN:
            self.toast(
                "Замер при активном TUN недоступен: независимый маршрут не обеспечен. Отключите TUN для проверки."
            )
            return False
        if self._subscription_busy:
            self.toast("Дождитесь обновления подписок")
            return False
        return True

    def keep_working_profiles(self, group_id: int) -> None:
        from src.ui.logic.latency import failed_profile_ids

        if not self._can_probe():
            return
        store = self.context.profiles

        def signature():
            return [(p.id, p.bean.to_share_link()) for p in store.get_profiles_in_group(group_id)]

        before = signature()
        ids = [profile_id for profile_id, _link in before]
        if not ids:
            return
        results = {}
        runner = self._ensure_latency_runner()

        def result(profile_id, value):
            results[profile_id] = value
            self._on_latency_result(profile_id, value)

        def finished():
            self._on_latency_done()
            if (
                signature() != before
                or not runner.last_run_complete
                or not self._network_available()
            ):
                self.toast("Фильтрация отменена: неполный замер, нет сети или группа изменилась")
                return
            removable = failed_profile_ids(
                ids, results, complete=True, active_id=self.context.proxy_state.started_profile_id
            )
            working = sum(value >= 0 for value in results.values())
            if not removable:
                self.toast(f"Рабочих: {working} из {len(ids)}. Профили не удалены")
                return

            def remove():
                if signature() != before or self._subscription_busy or runner.is_busy:
                    self.toast("Группа изменилась; повторите проверку")
                    return
                for profile_id in removable:
                    if profile_id != self.context.proxy_state.started_profile_id:
                        store.remove_profile(profile_id)
                self.save_profiles()

            self._shell.confirm(
                CONFIRM_DELETE,
                "Оставить рабочие профили?",
                f"Рабочих: {working} из {len(ids)}. Будет удалено: {len(removable)}. Активный профиль сохраняется.",
                remove,
                confirm_label="Оставить рабочие",
            )

        if not runner.run(ids, on_result=result, on_done=finished):
            self.toast("Проверка задержки уже идёт")

    def test_latency(self) -> None:
        if not self._can_probe():
            return
        profile_ids = list(self.context.profiles.profiles)
        if not profile_ids:
            self.toast("Нет профилей для проверки")
            return

        runner = self._ensure_latency_runner()
        started = runner.run(
            profile_ids,
            on_result=self._on_latency_result,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")
            return

        by_group: dict[int, list[int]] = {}
        for profile_id in profile_ids:
            profile = self.context.profiles.get_profile(profile_id)
            if profile is not None:
                by_group.setdefault(profile.group_id, []).append(profile_id)
        self._show_ping_progress(PingProgress(by_group))
        self.toast(f"Проверяю задержку: {len(profile_ids)} профилей")

    def test_latency_for(self, profile_id: int) -> None:
        """Measure the latency of one profile."""
        if not self._can_probe():
            return
        if self.context.profiles.get_profile(profile_id) is None:
            self.toast("Профиль не найден")
            return

        runner = self._ensure_latency_runner()
        started = runner.run(
            [profile_id],
            on_result=self._on_latency_result,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")

    def test_latency_for_group(self, group_id: int) -> None:
        """Measure the latency of one group, ordering rows as results arrive."""
        if not self._can_probe():
            return
        store = self.context.profiles
        if store.get_group(group_id) is None:
            self.toast("Группа не найдена")
            return

        profile_ids = [profile.id for profile in store.get_profiles_in_group(group_id)]
        if not profile_ids:
            self.toast("В группе нет профилей")
            return

        # Пинг группы — единственный случай, когда порядок строк говорит о
        # результате: список пересортировывается по задержке, пока идёт замер.
        self._shell.sort_by_ping()

        runner = self._ensure_latency_runner()
        started = runner.run(
            profile_ids,
            on_result=self._on_latency_result_live,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")
            return

        self._show_ping_progress(PingProgress({group_id: profile_ids}))
        self.toast(f"Проверяю задержку: {len(profile_ids)} профилей")

    def _show_ping_progress(self, progress: PingProgress | None) -> None:
        """Hand the progress of a run to the group rows; None hides it."""
        self._ping_progress = progress
        self._shell.set_ping_progress(progress)

    def _on_latency_result(self, profile_id: int, latency_ms: int) -> None:
        profile = self.context.profiles.get_profile(profile_id)
        if profile is not None:
            profile.latency_ms = latency_ms

        if self._ping_progress is None:
            return
        group_id = self._ping_progress.record(profile_id)
        if group_id is not None:
            self._shell.update_group_progress(group_id)

    def _on_latency_result_live(self, profile_id: int, latency_ms: int) -> None:
        """Store one result and schedule a re-sort of the list.

        Перерисовка склеивается по таймеру: список должен пересортировываться
        по ходу замера, но на группе в сотни профилей построчный refresh занял
        бы секунды главного цикла и превратил бы обновление в рывки.
        """
        self._on_latency_result(profile_id, latency_ms)
        self._schedule_latency_refresh()

    def _schedule_latency_refresh(self) -> None:
        if not self._shell.has_window() or self._latency_refresh_handle is not None:
            return

        def _redraw() -> bool:
            self._latency_refresh_handle = None
            self._shell.refresh_pages()
            return False

        self._latency_refresh_handle = self._loop.schedule(LATENCY_REFRESH_INTERVAL_MS, _redraw)

    def _cancel_latency_refresh(self) -> None:
        if self._latency_refresh_handle is not None:
            self._loop.cancel(self._latency_refresh_handle)
            self._latency_refresh_handle = None

    def _on_latency_done(self) -> None:
        # Итоговая перерисовка всё равно будет ниже: отложенная только
        # продублировала бы её уже после сохранения.
        self._cancel_latency_refresh()
        self._show_ping_progress(None)
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist latency results: %s", e)

        self._shell.refresh_pages()
        self.toast("Проверка задержки завершена")
```

Замечание про `_redraw`: в GTK он возвращал `GLib.SOURCE_REMOVE` (это `False`); `MainLoop.schedule` ждёт `bool`, значение то же.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: PASS

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): AppController — замер задержки и «оставить рабочие»"
```

---

### Task 7: Контроллер — обновления и ссылки приложения

**Files:**
- Modify: `src/ui/controller.py` (секция «обновления и ссылки»)
- Test: `tests/test_ui_controller.py`

**Step 1: Write the failing test** (добавить в конец файла)

```python
# --- обновления и ссылки ---


def test_app_update_is_notified_once(tmp_path):
    from tests.test_core_app_update import RELEASE

    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    controller = AppController(context, shell, ImmediateLoop(), app_version=lambda: "0.16.2")
    calls = []
    controller.set_app_release_fetcher(lambda: calls.append(True) or [RELEASE])

    controller.refresh_app_releases_if_due()
    controller.app_update_thread.join(5)
    controller.refresh_app_releases_if_due()

    assert context.config.app_update_notified == "v0.17.0"
    assert shell.last_toast == "Доступна версия v0.17.0. Откройте настройки → О программе"
    assert calls == [True]


def test_app_update_is_skipped_without_a_fetcher(made):
    controller, _shell, _ = made

    controller.refresh_app_releases_if_due()

    assert controller.app_update_thread is None


def test_core_releases_are_refreshed_when_due(made, monkeypatch):
    controller, _shell, _ = made
    monkeypatch.setattr("src.ui.controller.is_check_due", lambda _config, _now: True)
    seen = []
    monkeypatch.setattr(
        "src.ui.controller.refresh_known_releases",
        lambda config, *, now, fetch: seen.append(fetch()) or None,
    )
    controller.set_release_fetcher(lambda: ["r"])

    controller.refresh_core_releases_if_due()
    controller.core_update_thread.join(5)

    assert seen == [["r"]]


def test_subscription_link_opens_the_form_prefilled(made):
    from urllib.parse import quote

    controller, shell, _ = made

    controller.import_app_link("veblock://add/" + quote("https://example.com/sub", safe="") + "#Example")

    assert shell.forms == [("subscription", "Example", "https://example.com/sub")]


def test_routing_link_asks_for_confirmation_then_applies(made):
    import base64
    import json

    controller, shell, _ = made
    payload = base64.urlsafe_b64encode(
        json.dumps({"DirectSites": ["example.org"], "GlobalProxy": False}).encode()
    ).decode()

    controller.import_app_link("happ://routing/add/" + payload)

    kind, rows, on_confirm = shell.forms[-1]
    assert kind == "routing-import" and rows
    on_confirm()
    assert "example.org" in controller.context.config.routing.direct_list
    assert shell.toasts[-1] == ("Маршрутизация импортирована", "Вернуть", "app.restore-routing")
    assert shell.enabled["restore-routing"] is True


def test_broken_link_only_toasts(made):
    controller, shell, _ = made

    controller.import_app_link("veblock://add/\x01")

    assert shell.last_toast and shell.forms == []
```

Если `test_routing_link_asks_for_confirmation_then_applies` падает на `direct_list` (поле может называться иначе или хранить правила с префиксом), свериться с `tests/test_ui_application.py::test_routing_import_requires_confirmation` и использовать ту же проверку.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider -k "update or release or link"`
Expected: FAIL, `AttributeError: ... 'set_app_release_fetcher'`

**Step 3: Write minimal implementation**

В секцию «обновления и ссылки»:

```python
    def set_release_fetcher(self, fetch: Callable[[], object] | None) -> None:
        """Install the function asking GitHub about core releases.

        Без неё приложение в сеть за релизами не ходит: её ставит только
        `run_app`, поэтому тесты и встраивание остаются без сетевых запросов.
        """
        self._release_fetcher = fetch

    def refresh_core_releases_if_due(self) -> None:
        """Remember the newest core releases, at most once in a few days.

        Только запоминает: о новой версии говорит страница «О программе».
        """
        if not self.context.config.core_update_enabled:
            return
        fetch = self._release_fetcher
        config = self.context.config
        if fetch is None or not is_check_due(config, time.time()):
            return
        if self.core_update_thread is not None and self.core_update_thread.is_alive():
            return

        self.core_update_thread = run_in_background(
            lambda: refresh_known_releases(config, now=time.time(), fetch=fetch),
            on_done=lambda _releases: self.context.save_config(),
            # Нет сети — спросим при следующем запуске.
            on_error=lambda _error: None,
            dispatch=self._loop.dispatch,
            name="tenga-core-update",
        )

    def set_app_release_fetcher(self, fetcher) -> None:
        self._app_release_fetcher = fetcher

    def refresh_app_releases_if_due(self) -> None:
        from src.core.app_update import CHECK_INTERVAL_SECONDS, check_app_update

        context = self.context
        config = context.config
        if (
            self._app_release_fetcher is None
            or not config.app_update_enabled
            or (self.app_update_thread and self.app_update_thread.is_alive())
            or (
                config.app_update_last_attempt
                and time.time() - config.app_update_last_attempt < CHECK_INTERVAL_SECONDS
            )
        ):
            return

        def work():
            return check_app_update(
                config,
                self._app_version(),
                fetch=self._app_release_fetcher,
            )

        def done(release):
            if release and config.app_update_notified != release.version:
                self.toast(f"Доступна версия {release.version}. Откройте настройки → О программе")
                config.app_update_notified = release.version
            context.save_config()

        self.app_update_thread = run_in_background(
            work,
            on_done=done,
            on_error=lambda _error: context.save_config(),
            dispatch=self._loop.dispatch,
            name="tenga-app-update",
        )

    def import_app_link(self, raw: str) -> None:
        from src.fmt.app_links import parse_app_link

        try:
            link = parse_app_link(raw, exceptions=self.context.config.sub_source_exceptions)
        except ValueError as error:
            self.toast(str(error))
            return
        if link.operation == "unsupported":
            self.toast("VK-туннель пока не поддерживается в десктопной версии")
        elif link.operation == "subscription":
            self._shell.open_subscription_form(link.name, link.url)
        else:
            from src.ui.logic.routing_import import effective_routing, import_rows

            config, config_dir = self.context.config, self.context.config_dir
            rows = import_rows(
                effective_routing(config.routing, config_dir),
                link.routing,
                name=link.name,
                direct_default=link.direct_default,
            )
            self._shell.open_routing_import(
                rows, lambda: self.apply_routing_import(link.routing)
            )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov -p no:cacheprovider`
Expected: PASS

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): AppController — проверка обновлений и импорт ссылок"
```

---

### Task 8: `TengaApplication` поверх контроллера

Самая ответственная задача: поведение на Linux не меняется, а существующие GTK-тесты — единственный способ это доказать. Тестов на этой задаче не пишется: контракт уже закреплён в `tests/test_ui_application.py`, `tests/test_ui_window.py`, `tests/test_ui_tray_controller.py`.

**Files:**
- Modify: `src/ui/application.py`

**Step 1: Прогнать GTK-тесты до правки** — должны быть зелёными (ориентир из задачи 0).

**Step 2: Импорты.** Убрать неиспользуемые после переноса и добавить новые. Итоговый блок импортов `src/ui/application.py`:

```python
from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from src.core import platform_info
from src.core.context import AppContext, get_context
from src.core.core_update import fetch_releases
from src.core.main_loop import GLibLoop
from src.ui.controller import CONFIRM_URL_CHANGE, AppController, resume_monitoring
from src.ui.logic.profiles_view import SortKey
from src.ui.logic.version import app_version, core_version
from src.ui.window import APP_ICON, MainWindow, apply_theme, load_css, load_icons

if TYPE_CHECKING:
    from collections.abc import Callable
```

Удалить константу `LATENCY_REFRESH_INTERVAL_MS` (теперь в контроллере). `_network_available` и `_ACCELS` остаются.

**Step 3: Класс `_GtkShell`** — перед `class TengaApplication`:

```python
class _GtkShell:
    """`Shell` контроллера поверх `TengaApplication`: окно, трей, диалоги, действия.

    Все обращения к окну идут через `app._window` в момент вызова: окно
    создаётся при активации и исчезает в `reset_for_tests`.
    """

    def __init__(self, app: TengaApplication) -> None:
        self._app = app

    def _window(self):
        return self._app._window

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._app.toast(text, button=button, action=action)

    def notify(self, text: str) -> None:
        self._app.last_notification_for_test = text
        notification = Gio.Notification.new("Veblock")
        notification.set_body(text)
        self._app.send_notification(FAILOVER_NOTIFICATION_ID, notification)

    def has_window(self) -> bool:
        return self._window() is not None

    def refresh_status(self) -> None:
        window = self._window()
        if window is not None:
            window.refresh_status()

    def refresh_pages(self) -> None:
        window = self._window()
        if window is not None:
            window.refresh_pages()

    def show_connecting(self, profile_name: str) -> None:
        window = self._window()
        if window is not None:
            window.show_connecting(profile_name)

    def show_error(self, message: str) -> None:
        window = self._window()
        if window is not None:
            window.show_error(message)

    def selected_profile_id(self) -> int | None:
        window = self._window()
        if window is None:
            return None
        return window.profiles_page.get_selected_profile_id()

    def sort_by_ping(self) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.set_sort(SortKey.PING, ascending=True)

    def set_ping_progress(self, progress) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.set_ping_progress(progress)

    def update_group_progress(self, group_id: int) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.update_group_progress(group_id)

    def set_tray_state(self, state, profile_name: str) -> None:
        if self._app.tray is not None:
            self._app.tray.set_state(state, profile_name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        action = self._app.lookup_action(name)
        if action is not None:
            action.set_enabled(enabled)

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None) -> None:
        from src.ui.dialogs.confirm import (
            build_delete_confirmation,
            build_url_change_confirmation,
        )

        if kind == CONFIRM_URL_CHANGE:
            dialog = build_url_change_confirmation(heading, body, on_confirm)
        else:
            dialog = build_delete_confirmation(
                heading, body, on_confirm, confirm_label=confirm_label or "Удалить"
            )
        self._app.present_dialog(dialog)

    def open_subscription_form(self, name: str, url: str) -> None:
        from src.ui.dialogs.subscription import SubscriptionDialog

        dialog = SubscriptionDialog()
        dialog.name_row.set_text(name)
        dialog.url_row.set_text(url)
        dialog.connect(
            "subscription-ready", lambda _d, n, u: self._app.add_subscription(n, u)
        )
        self._app.present_dialog(dialog)

    def open_routing_import(self, rows, on_confirm) -> None:
        from src.ui.dialogs.routing_import import RoutingImportDialog

        self._app.present_dialog(RoutingImportDialog(rows, on_confirm))
```

**Step 4: Конструктор `TengaApplication`.** Заменить поля состояния на контроллер. Итоговый `__init__` после `super().__init__(...)`:

```python
        self.context = context or get_context()
        self._lock = lock
        self._lock_path = lock_path
        self._activation = None
        self.tray = None
        self._with_tray = with_tray
        self._signal_source_ids: list[int] = []
        self._window: MainWindow | None = None
        self._dialog = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        self.controller = self._make_controller()

    def _make_controller(self) -> AppController:
        return AppController(
            self.context,
            _GtkShell(self),
            GLibLoop(),
            network_available=_network_available,
            # Лямбда, а не ссылка: тесты подменяют `app_version` в этом модуле.
            app_version=lambda: app_version(),
        )
```

**Step 5: Жизненный цикл.** В `do_activate` заменить три последних вызова:

```python
        self.resume_monitoring()
        self.controller.refresh_core_releases_if_due()
        self.controller.refresh_app_releases_if_due()
```

В `do_shutdown` заменить блок `if self._connection_service is not None: ...` на `self.controller.shutdown()`.

**Step 6: Делегаты.** Удалить из `TengaApplication` тела перенесённых методов и заменить их делегатами. Удалить совсем (их больше никто не зовёт снаружи): `_refresh_app_releases_if_due`, `_refresh_core_releases_if_due`, `_ensure_connection_service`, `_connection_busy`, `_connect_selected`, `_toggle_connection`, `_selected_profile_id`, `_on_connection_done`, `_on_disconnection_done`, `_on_connection_failed`, `_refresh_window`, `_apply_routing_import`, `_sync_restore_routing`, `_save_profiles`, `_refresh_pages`, `_propose_fallback_url`, `_offer_url_change`, `_apply_url_change`, `_ensure_latency_runner`, `_can_probe`, `_test_latency`, `_show_ping_progress`, `_on_latency_result`, `_on_latency_result_live`, `_schedule_latency_refresh`, `_cancel_latency_refresh`, `_on_latency_done`, `_refresh_subscriptions`, `_on_subscriptions_updated`, `_on_subscriptions_failed`.

Оставить как делегаты (одна строка тела каждый):

```python
    # --- делегаты контроллера: их зовут окно, трей, run_app и тесты ---

    def set_app_release_fetcher(self, fetcher) -> None:
        self.controller.set_app_release_fetcher(fetcher)

    def set_release_fetcher(self, fetch) -> None:
        self.controller.set_release_fetcher(fetch)

    def import_app_link(self, raw: str) -> None:
        self.controller.import_app_link(raw)

    def resume_monitoring(self) -> None:
        # Функция модуля, а не метод контроллера: тест монитора зовёт этот
        # метод на SimpleNamespace, у которого есть только `context`.
        resume_monitoring(self.context)

    def watch_monitor(self) -> None:
        self.controller.watch_monitor()

    def notify_user(self, text: str) -> None:
        self.controller.notify_user(text)

    def set_connection_service(self, service) -> None:
        self.controller.set_connection_service(service)

    def connect_profile(self, profile_id: int) -> None:
        self.controller.connect_profile(profile_id)

    def disconnect_proxy(self) -> None:
        self.controller.disconnect_proxy()

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        return self.controller.add_profile_from_bean(bean, group_id=group_id)

    def delete_profile(self, profile_id: int) -> None:
        self.controller.delete_profile(profile_id)

    def add_subscription(self, name: str, url: str):
        return self.controller.add_subscription(name, url)

    def add_group(self, name: str):
        return self.controller.add_group(name)

    def update_group(self, group_id: int, *, name: str, url: str | None = None):
        return self.controller.update_group(group_id, name=name, url=url)

    def delete_group(self, group_id: int) -> None:
        self.controller.delete_group(group_id)

    def save_profiles(self) -> None:
        self.controller.save_profiles()

    def apply_settings(self) -> bool:
        return self.controller.apply_settings()

    def restore_routing(self) -> None:
        self.controller.restore_routing()

    def reconnect_current(self) -> None:
        self.controller.reconnect_current()

    def set_latency_probe(self, probe) -> None:
        self.controller.set_latency_probe(probe)

    def set_subscription_updater(self, updater) -> None:
        self.controller.set_subscription_updater(updater)

    def set_profile_activation_handler(self, handler) -> None:
        self.controller.set_profile_activation_handler(handler)

    def select_profile(self, profile_id: int) -> None:
        self.controller.select_profile(profile_id)

    def update_subscription(self, group_id: int) -> None:
        self.controller.update_subscription(group_id)

    def keep_working_profiles(self, group_id: int) -> None:
        self.controller.keep_working_profiles(group_id)

    def test_latency_for(self, profile_id: int) -> None:
        self.controller.test_latency_for(profile_id)

    def test_latency_for_group(self, group_id: int) -> None:
        self.controller.test_latency_for_group(group_id)

    # Имена с подчёркиванием читают существующие тесты.

    def _default_subscription_updater(self, group_id: int, url: str) -> int:
        return self.controller.default_subscription_updater(group_id, url)

    @property
    def _app_update_thread(self):
        return self.controller.app_update_thread
```

**Step 7: Действия.** В `_register_actions` словарь `handlers`:

```python
        # Лямбды, а не связанные методы: `reset_for_tests` создаёт новый
        # контроллер, и действия должны разыменовывать `self.controller`
        # в момент вызова, иначе кликали бы в контроллер прежнего контекста.
        handlers: dict[str, Callable[[], None]] = {
            "connect": lambda: self.controller.connect_selected(),
            "disconnect": lambda: self.controller.disconnect_proxy(),
            "toggle-connection": lambda: self.controller.toggle_connection(),
            "add-profile": self._open_add_profile,
            "add-profile-from-clipboard": self._add_profile_from_clipboard,
            "add-subscription": self._open_add_subscription,
            "add-group": self._open_add_group,
            "refresh-subscriptions": lambda: self.controller.refresh_subscriptions(),
            "test-latency": lambda: self.controller.test_latency(),
            "search": self._toggle_search,
            "settings": self._open_settings,
            "about": self._open_about,
            "shortcuts": self._open_shortcuts,
            "quit": self.quit,
            "hide-window": self._hide_window,
            "activate-window": self._activate_window,
            "restore-routing": lambda: self.controller.restore_routing(),
        }
```

Действие с параметром: `connect_profile.connect("activate", lambda _action, param: self.controller.connect_profile(param.get_int32()))`. После цикла регистрации заменить `self._sync_restore_routing()` на `self.controller.sync_restore_routing()`.

**Step 8: Диалоги приложения.** В `_open_add_profile`, `_open_add_subscription`, `_open_add_group`, `_open_settings` колбэки сигналов уже зовут публичные делегаты (`self.add_profile_from_bean`, `self.add_subscription`, `self.add_group`, `self.apply_settings`) — оставить как есть. Удалить `_save_and_apply` (не используется). `_open_about` без изменений.

**Step 9: Тестовые ожидания.** Переписать на поля контроллера:

```python
    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.core_update_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    def wait_for_connection_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.connection_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    def wait_for_latency_for_test(self, timeout: float = 10.0) -> None:
        runner = self.controller.latency_runner
        if runner is not None:
            runner.wait(timeout)
        self._drain_main_context()

    def wait_for_subscriptions_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.subscriptions_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    @staticmethod
    def _drain_main_context() -> None:
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
```

**Step 10: `reset_for_tests`:**

```python
    def reset_for_tests(self, context: AppContext | None) -> None:
        """Rebind the application to another context and drop the window.

        Существует ради тестов: создать второе приложение нельзя, GApplication
        занимает путь на шине сессии до конца процесса.
        """
        self.stop_tray()
        if self._window is not None:
            self._window.detach()
            self._window.destroy()
            self._window = None
        if context is not None:
            self.context = context
        self.controller = self._make_controller()
        self._dialog = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        # Действие пережило бы смену контекста с состоянием прежнего.
        self.controller.sync_restore_routing()
```

**Step 11: `_start_activation_server`** — тело `deliver` без изменений: `self.import_app_link(uri)` теперь делегат.

**Step 12: Проверка.**

```bash
python cli.py lint-all
uv run pytest -q --no-cov -p no:cacheprovider
make test-gtk
make test-tray
grep -n "def _refresh_window\|def _ensure_latency_runner\|_latency_runner\b\|_subscription_busy\|_url_proposals" src/ui/application.py
```

Expected: lint чистый; все наборы зелёные с числами не меньше, чем в задаче 0; последний `grep` ничего не находит (состояния оркестровки в приложении не осталось). Если какой-то GTK-тест упал — искать расхождение поведения в контроллере (порядок тостов, проверка окна, имя действия), а не править тест.

**Step 13: Ручная проверка на Linux.** Запустить `python gui.py`, подключиться к профилю в режиме системного прокси (не TUN), отключиться, обновить подписку, замерить задержку группы, открыть настройки и закрыть. Трей: подключение из меню трея, «Показать окно». Ожидается прежнее поведение.

**Step 14: Commit**

```bash
git add src/ui/application.py
git commit -m "refactor(ui): TengaApplication — тонкая оболочка над AppController"
```

---

### Task 9: Документация и статус фазы

**Files:**
- Modify: `CLAUDE.md` (раздел «Key Design Patterns»)
- Modify: `AGENTS.md` (если в нём дублируется описание архитектуры — `grep -n "AppContext\|XrayManager" AGENTS.md`)
- Modify: `docs/plans/2026-10-28-windows-qt-frontend-design.md` (раздел «Границы»)
- Modify: `docs/plans/2026-10-28-windows-qt-phase1-controller.md` (этот файл, раздел «Статус»)
- Modify: `docs/ru/development.md`, `docs/en/development.md` (если описывают `application.py`: `grep -n "application.py" docs/ru/development.md docs/en/development.md`)

**Step 1:** В `CLAUDE.md` после блока про `AppContext` добавить:

```markdown
**AppController (`src/ui/controller.py`)** - оркестровка приложения без GTK:
- Подключение, профили и группы, подписки и смена адреса, замер задержки,
  failover, проверка обновлений, импорт ссылок приложения
- С интерфейсом говорит через протокол `Shell` (тосты, уведомления,
  обновление окна, подтверждения, формы), с главным потоком — через
  `MainLoop` из `src/core/main_loop.py` (`GLibLoop` в GTK, `ImmediateLoop`
  в тестах)
- `TengaApplication` — тонкая оболочка: `Gio.SimpleAction`, окно, трей,
  слот диалога, `_GtkShell`; публичные методы приложения — делегаты
- Тестируется обычным pytest с подменной оболочкой (`tests/test_ui_controller.py`)

**MainLoop (`src/core/main_loop.py`)** - главный цикл как зависимость:
`dispatch` (один раз в главном потоке), `schedule` (таймер, повтор пока
True), `cancel`. `ConnectionMonitor` и `AppController` получают его
параметром; GLib импортируется лениво при каждом вызове, чтобы подмены
в тестах действовали.
```

**Step 2:** В дизайн-документе, раздел «Границы», абзац «Без изменений»: убрать `src/core` из списка нетронутого и добавить строку:

```markdown
**Уточнение по итогам фазы 1:** `src/core/monitor.py` вызывал GLib напрямую
(`idle_add`, `timeout_add`, `source_remove`). Главный цикл вынесен в
`src/core/main_loop.py` и передаётся монитору параметром; поведение в GTK
прежнее. Остальной `src/core` без изменений.
```

**Step 3:** В конец этого плана добавить раздел:

```markdown
## Статус

Код фазы выполнен (дата), задачи 1–9. Числа тестов до/после:
обычный pytest N/N, `make test-gtk` N/N, `make test-tray` N/N. Ожидания
существующих тестов не менялись.

Отклонения от плана:

- (заполняется исполнителем)
```

**Step 4:** Проверить и закоммитить:

```bash
python cli.py lint-all
uv run pytest -q --no-cov -p no:cacheprovider
git add CLAUDE.md AGENTS.md docs/
git commit -m "docs: AppController и MainLoop в архитектуре, статус фазы 1"
```

---

## Что намеренно не делается в этой фазе

- Трей остаётся на `GLib.idle_add` в `src/ui/tray/win32/item.py` и `controller.py`: Win32-трей удаляется в фазе 4, а `TrayController` уже принимает `dispatch` параметром.
- `_default_dispatch` в `async_utils.py` и `latency.py` остаются: контроллер передаёт `dispatch` явно, значения по умолчанию нужны прочим вызывающим на GTK.
- `src/ui/qt/` не создаётся — это фаза 2.
- `tests/test_ui_platform_branches.py` не меняется: контроллер не читает `IS_WINDOWS`.

## Статус

Код фазы выполнен 28.10.2026, задачи 0–9. Числа тестов до/после:
обычный pytest 1530/1583 passed (10 skipped в обоих прогонах; +53 новых
теста: 8 в `test_core_main_loop.py`, 3 в `test_core_monitor.py`, 42 в
`test_ui_controller.py`), `make test-gtk` 279/279, `make test-tray`
146/146 (5 skipped). Ожидания существующих тестов не менялись.

Отклонения от плана:

- Фикстура `made` в `tests/test_ui_controller.py` загружает
  `context.config`: настройки грузятся лениво, и без загрузки
  `save_config()` возвращает False. В живом приложении их загружает окно.
- Таймеры монитора аннотированы `object | None` вместо `int | None`:
  дескриптор выдаёт `MainLoop.schedule`, в `ImmediateLoop` это кортеж.
- Числа в шагах «Expected» разошлись с фактом: в задаче 1 тестов 8, а не 7
  (параметризованный тест даёт три случая), в задаче 3 — 14, а не 15
  (ошибка подсчёта в плане). Состав тестов совпадает с планом.
- Ручная проверка с подключением (шаг 13 задачи 8) не выполнялась: на машине
  разработчика работает живая TUN-сессия, а смена системного прокси задела бы
  её. Вместо неё GUI запущен под xvfb с отдельным `TENGA_CONFIG_DIR`: окно
  поднимается, в журнале нет предупреждений и ошибок, поведение при
  завершении такое же, как до правки. Подключение, трей и подписки на живом
  рабочем столе остаются за ручной проверкой.
