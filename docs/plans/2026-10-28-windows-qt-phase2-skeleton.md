# Фаза 2: каркас Qt-интерфейса — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Запустить Veblock на PySide6 из исходников обычным Python — главное окно (карточка, дерево серверов, мониторинг, поиск, тост), подключение и отключение, трей, — на Windows по умолчанию и на Linux по `--ui qt`, не меняя GTK-интерфейс.

**Architecture:** `src/ui/qt/` — тонкая оболочка над `AppController` из фазы 1: `QtLoop` реализует `MainLoop` поверх очереди событий Qt, `_QtShell` — протокол `Shell`, `QtApplication` держит `QAction` с теми же именами, что `Gio.SimpleAction` в GTK, поэтому `TrayController` и модель меню трея работают без изменений через новый `QtTrayItem`. Вся логика представления берётся из `src/ui/logic/` (`status_view`, `build_profile_rows`, `monitoring_view`, геометрия). `gui.py` выбирает интерфейс до инициализации GTK.

**Tech Stack:** Python 3.11+, PySide6-Essentials ≥ 6.8 (проверено на 6.12), `QT_QPA_PLATFORM=offscreen` для тестов, pytest, ruff.

**Дизайн:** `docs/plans/2026-10-28-windows-qt-frontend-design.md`, разделы «Фронтенд Qt», «Главное окно», «Трей», «Запуск и единственность», фаза 2.
**Предыдущая фаза:** `docs/plans/2026-10-28-windows-qt-phase1-controller.md`.

---

## Правила фазы

- **Критерий приёмки:** `uv run pytest`, `make test-gtk`, `make test-tray`, `make test-qt`, `python cli.py lint-all` зелёные; ожидания существующих тестов не правятся; `python gui.py --ui qt` на Linux открывает окно, подключается и отключается в режиме системного прокси; на VM Windows 10 и 11 `python gui.py` из исходников делает то же (задача 11).
- GTK-интерфейс и Linux-поведение не меняются. `src/ui/application.py`, `src/ui/window.py` и прочий GTK-код в этой фазе не трогается.
- Qt-модули не импортируют `gi` и не читают `IS_WINDOWS` (`tests/test_ui_platform_branches.py` не расширяется): различие ОС — в `gui.py`, вне `src/ui`.
- Каждый Qt-тестовый файл начинается с `pytest.importorskip("PySide6")` и `pytestmark = pytest.mark.qt`: обычный прогон и CI без PySide6 их пропускают.
- Один коммит на задачу, сообщения на русском в стиле репозитория. Перед коммитом: `uv run pytest -q --no-cov -p no:cacheprovider`, `make test-qt` (с задачи 2), `python cli.py lint-all`.
- Не запускать xray с TUN-конфигами на машине разработчика (интерфейс `xray0` занят рабочим подключением).
- Код плана проверен: файлы собраны и прогнаны в отдельном worktree (Qt 6.12, offscreen) — 50 Qt-тестов, обычный pytest, `make test-gtk`, `make test-tray`, lint.

## Решения фазы (уточняют дизайн)

| Вопрос | Решение | Почему |
|---|---|---|
| pytest-qt | **не используется**; своя фикстура `qapp` в `tests/conftest.py` и `tests/support/qt.py` (`process_events`, `wait_until`) | плагин pytest-qt без установленного PySide6 роняет весь pytest («No module named PySide6»), а `dev` ставится в CI Linux и без Qt |
| Группа зависимостей | `windows = [PySide6-Essentials>=6.8, pywin32; sys_platform=='win32']`; PyGObject и pycairo получают маркер `sys_platform != 'win32'` | иначе `uv sync` на Windows собирает PyGObject без GTK и падает |
| `QtNetwork` | **остаётся** (`QNetworkInformation` для failover) | в Essentials он есть; без него failover переключал бы профиль при выключенной сети. Исключение QtNetwork из spec в фазе 4 отменяется |
| Тост | строка в компоновке над поиском, а не поверх дерева | наложение с ручным позиционированием не окупается; видимо и не закрывает дерево |
| Диалоги, «Добавить», настройки | действия зарегистрированы, но показывают тост «Раздел появится в следующей сборке»; `open_subscription_form`/`open_routing_import` оболочки — то же | окна приходят в фазе 3; трей и сочетания не должны попадать в «неизвестное действие» |
| Сворачивание в трей | есть трей → закрытие прячет окно, нет трея → завершает приложение; настройки нет | настройка «Сворачивать в трей» — фаза 3 вместе с окном настроек |
| Видимость панели мониторинга | не запоминается | новое поле настроек — фаза 3 |
| Счётчик группы | в колонке «Пинг», во время замера — «готово / всего» | там же GTK показывает прогресс замера группы |
| Флаг в карточке состояния | имя профиля как есть (эмодзи) | виджет имени с картинкой флага — фаза 3; в дереве и меню трея флаги уже картинками |
| Вторая копия `--ui qt` на Linux | печатает «Veblock уже запущен» и выходит с кодом 1 | D-Bus-активации GApplication у Qt нет; на Windows работает прежний pipe активации |
| Windows-установщик из CI | после этой фазы запускает Qt без PySide6 и неработоспособен | решение 6 дизайна: Windows-релизов нет до готовности Qt; spec и CI — фаза 4 |

## Что уже есть и переиспользуется без изменений

- `AppController`, `Shell`, `resume_monitoring` — `src/ui/controller.py`.
- `MainLoop` — `src/core/main_loop.py`; `attach_monitor(context, loop=...)` — `src/core/monitor.py`.
- `TrayController(application, context, *, item, dispatch)` — `src/ui/tray/controller.py`: элемент и диспетчер передаются параметрами; приложению нужен только `activate_action(name, target)`.
- `build_menu`, `MenuItem` — `src/ui/tray/menu.py`, `src/ui/tray/dbusmenu.py`; `icon_name_for`, `icons_directory` — `src/ui/tray/icons.py`.
- `status_view`, `ConnectionState` — `src/ui/logic/status.py`; `build_profile_rows`, `SortKey`, `ping_text` — `profiles_view.py`; `monitoring_view` — `monitoring_view.py`; `parse_geometry`/`format_geometry` — `geometry.py`; `pending_settings` — `settings_state.py`; `normalize_theme` — `appearance.py`; `split_flag_prefix` — `country_flags.py`; `PingProgress` — `latency.py`.
- Картинки: `assets/icons/win/monolith-{connected,connecting,disconnected,error}.png` (карточка), `assets/icons/win/tenga-proxy-*.ico` (трей), `assets/flags/<код>.svg` (флаги), `assets/tenga-proxy.ico` (окно).

---

### Task 0: Сверка с кодом

**Files:** только чтение.

**Step 1:** Убедиться, что фаза 1 на месте и интерфейсы, на которые опирается план, не сдвинулись:

```bash
grep -n "class AppController\|class Shell\|def resume_monitoring" src/ui/controller.py
grep -n "def attach_monitor" src/core/monitor.py
grep -n "def __init__" -A8 src/ui/tray/controller.py | head -12
grep -n "# --- GTK bootstrap ---" gui.py
python3 -c "import PySide6" 2>&1 | tail -1
```

Expected: все определения найдены; `attach_monitor(context, loop=None)`; `TrayController` принимает `item` и `dispatch`; маркер в `gui.py` есть; PySide6 в окружении проекта ещё нет.

**Step 2:** Зафиксировать числа (ориентир на 28.10.2026 после фазы 1):

```bash
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -1   # 1583 passed, 10 skipped
make test-gtk 2>&1 | grep -E "passed|failed" | tail -1          # 279 passed
make test-tray 2>&1 | tail -1                                    # 146 passed, 5 skipped
```

---

### Task 1: Зависимости, маркер `qt`, фикстура `qapp`

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (генерируется)
- Modify: `tests/conftest.py` (фикстура в конец файла)
- Create: `tests/support/qt.py`

**Step 1:** Применить к `pyproject.toml`:

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 95ff453..a9a6c95 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -20,9 +20,10 @@ dependencies = [
     "grpcio-tools>=1.76.0",
     "idna>=3.11",
     "protobuf>=6.33.1",
-    "pycairo>=1.29.0",
+    # GTK-интерфейс Linux; на Windows интерфейс на Qt (группа windows).
+    "pycairo>=1.29.0; sys_platform != 'win32'",
     "Pygments>=2.19.2",
-    "PyGObject>=3.54.5",
+    "PyGObject>=3.54.5; sys_platform != 'win32'",
     "PyYAML>=6.0.3",
     "requests>=2.32.5",
     "typing_extensions>=4.15.0",
@@ -38,6 +39,12 @@ dev = [
     "ruff>=0.8.0",
     "isort>=5.13.0",
 ]
+# Интерфейс Windows (docs/plans/2026-10-28-windows-qt-frontend-design.md).
+# На Linux ставится по желанию: `--ui qt` и `make test-qt`.
+windows = [
+    "PySide6-Essentials>=6.8",
+    "pywin32>=308; sys_platform == 'win32'",
+]
 build = [
     "pyinstaller>=6.17.0",
     "pyinstaller-hooks-contrib>=2025.10",
@@ -54,13 +61,14 @@ addopts = [
     "--cov-report=term-missing",
     "--cov-report=html",
     "-m",
-    "not gtk",
+    "not gtk and not qt",
 ]
 testpaths = ["tests"]
 python_files = ["test_*.py"]
 markers = [
     "gtk: requires a display, run through make test-gtk",
     "windows: requires real Windows, skipped elsewhere",
+    "qt: Qt widgets, run through make test-qt",
 ]
 
 [tool.ruff]
```

**Step 2:** Обновить lock и окружение:

```bash
uv lock
uv sync --extra dev --extra windows
uv run python -c "import PySide6, gi; print(PySide6.__version__)"
```

Expected: в `uv.lock` добавлены `pyside6-essentials`, `shiboken6`, `pywin32` (с маркером win32); печатается версия ≥ 6.8.

**Step 3:** Фикстура в конец `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def qapp():
    """Один `QApplication` на прогон: Qt не даёт создать второй.

    Тесты Qt помечены `qt` и идут через `make test-qt` (offscreen); без
    PySide6 они пропускаются, а не падают на импорте.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["veblock-tests"])
    return app
```

**Step 4:** `tests/support/qt.py`:

```python
"""Ожидание событий Qt в тестах без pytest-qt.

pytest-qt не подходит: без установленного PySide6 его плагин роняет весь
pytest, а обычный прогон и CI Linux идут без Qt.
"""

from __future__ import annotations

import time
from collections.abc import Callable


def process_events() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    """Крутить цикл событий, пока условие не выполнится; иначе AssertionError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process_events()
        if predicate():
            return
        time.sleep(0.01)
    process_events()
    assert predicate(), "условие не выполнилось за отведённое время"
```

**Step 5:** Проверить, что обычный прогон не изменился:

```bash
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -1
```

Expected: те же числа, что в задаче 0.

**Step 6: Commit**

```bash
python cli.py lint-all
git add pyproject.toml uv.lock tests/conftest.py tests/support/qt.py
git commit -m "build: группа windows с PySide6, маркер qt для тестов интерфейса"
```

---

### Task 2: `QtLoop` — главный цикл Qt как `MainLoop`

**Files:**
- Create: `src/ui/qt/__init__.py`, `src/ui/qt/widgets/__init__.py`
- Create: `src/ui/qt/dispatch.py`
- Test: `tests/test_ui_qt_dispatch.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_dispatch.py`:

```python
"""QtLoop: доставка в главный поток и таймеры поверх Qt."""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from src.ui.qt.dispatch import QtLoop
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


def test_dispatch_from_a_worker_runs_on_the_main_thread(qapp):
    loop = QtLoop()
    seen = []

    worker = threading.Thread(
        target=lambda: loop.dispatch(lambda x: seen.append((x, threading.current_thread())), 1)
    )
    worker.start()
    worker.join()
    assert seen == []

    wait_until(lambda: seen)
    assert seen == [(1, threading.main_thread())]


def test_dispatch_ignores_the_return_value(qapp):
    loop = QtLoop()
    calls = []

    loop.dispatch(lambda: calls.append(1) or True)
    wait_until(lambda: calls)
    for _ in range(5):
        process_events()

    assert calls == [1]


def test_schedule_repeats_while_the_callback_returns_true(qapp):
    loop = QtLoop()
    ticks = []

    loop.schedule(5, lambda: ticks.append(1) or len(ticks) < 3)

    wait_until(lambda: len(ticks) == 3)
    for _ in range(10):
        process_events()
    assert len(ticks) == 3


def test_cancel_stops_the_timer(qapp):
    loop = QtLoop()
    ticks = []
    handle = loop.schedule(5, lambda: ticks.append(1) or True)

    loop.cancel(handle)
    loop.cancel(handle)  # повторная отмена не ошибка
    for _ in range(10):
        process_events()

    assert ticks == []


def test_monitor_runs_on_the_qt_loop(qapp, tmp_path):
    from src.core.context import AppContext
    from src.core.monitor import ConnectionMonitor

    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    loop = QtLoop()
    monitor = ConnectionMonitor(context, loop=loop)
    monitor._check_connections = lambda: True

    monitor.start()
    assert len(loop._timers) == 2
    monitor.stop()

    assert loop._timers == set()
```

**Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -m qt tests/test_ui_qt_dispatch.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ui.qt'`

**Step 3: Implementation**

`src/ui/qt/__init__.py`:

```python
"""Интерфейс на PySide6: Windows 10 и 11, на Linux — `--ui qt` для разработки."""
```

`src/ui/qt/widgets/__init__.py`:

```python
"""Виджеты Qt-интерфейса."""
```

`src/ui/qt/dispatch.py`:

```python
"""Главный цикл Qt как `MainLoop` (src/core/main_loop.py).

Монитор, контроллер и трей зовут `dispatch` из рабочих потоков. Сигнал с
`QueuedConnection` ставит вызов в очередь потока, которому принадлежит
объект; объект создаётся в главном потоке, поэтому вызов выполняется там.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot


class QtLoop(QObject):
    """`dispatch`, `schedule` и `cancel` поверх очереди событий Qt.

    Создавать в главном потоке после `QApplication`: таймерам нужен цикл
    событий потока-владельца.
    """

    _call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)
        # Таймер без ссылки собрал бы сборщик мусора, и он молча остановился бы.
        self._timers: set[QTimer] = set()

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        self._call.emit(lambda: fn(*args))

    @Slot(object)
    def _run(self, thunk: Callable[[], object]) -> None:
        thunk()

    def schedule(self, interval_ms: int, fn: Callable[[], bool]) -> object:
        timer = QTimer(self)
        timer.setInterval(interval_ms)

        def tick() -> None:
            if not fn():
                self.cancel(timer)

        timer.timeout.connect(tick)
        self._timers.add(timer)
        timer.start()
        return timer

    def cancel(self, handle: object) -> None:
        if handle in self._timers:
            self._timers.discard(handle)
            handle.stop()
            handle.deleteLater()
```

Почему сигнал, а не `QTimer.singleShot(0, fn)` из потока: `singleShot` из потока без цикла событий не срабатывает; сигнал с `QueuedConnection` доставляется в поток-владелец объекта (проверено: вызов из `threading.Thread` выполняется в `MainThread` после `processEvents`).

**Step 4: Run to verify it passes**

Run: та же команда. Expected: 5 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt tests/test_ui_qt_dispatch.py
git commit -m "feat(qt): QtLoop — главный цикл Qt как MainLoop"
```

---

### Task 3: Трей — `QtTrayItem`

**Files:**
- Create: `src/ui/qt/icons.py`
- Create: `src/ui/qt/tray.py`
- Test: `tests/test_ui_qt_tray.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_tray.py`:

```python
"""QtTrayItem: меню из модели трея, клики и иконки."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QSystemTrayIcon

from src.ui.logic.status import ConnectionState
from src.ui.qt.tray import QtTrayItem, icon_file
from src.ui.tray.controller import TrayController
from src.ui.tray.dbusmenu import MenuItem, separator
from src.ui.tray.icons import icons_directory
from src.ui.tray.menu import build_menu

pytestmark = pytest.mark.qt


def _labels(menu):
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def test_menu_follows_the_model(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu(
        [
            MenuItem("Статус", enabled=False),
            separator(),
            MenuItem("Подключить", action="app.connect"),
            MenuItem("Профили", children=[MenuItem("A", action="app.connect-profile", target=1)]),
            MenuItem("Скрытый", visible=False),
        ]
    )

    actions = item.menu.actions()
    assert _labels(item.menu) == ["Статус", "Подключить", "Профили"]
    assert actions[1].isSeparator()
    assert not actions[0].isEnabled()
    assert _labels(actions[3].menu()) == ["A"]


def test_triggered_entry_reports_action_and_target(qapp):
    item = QtTrayItem(available=lambda: True)
    seen = []
    item.set_on_activate(lambda name, target: seen.append((name, target)))
    item.set_menu(
        [MenuItem("Профили", children=[MenuItem("A", action="app.connect-profile", target=7)])]
    )

    item.menu.actions()[0].menu().actions()[0].trigger()

    assert seen == [("app.connect-profile", 7)]


def test_checked_entry_is_checkable(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu([MenuItem("A", action="app.connect-profile", target=1, checked=True)])

    action = item.menu.actions()[0]
    assert action.isCheckable() and action.isChecked()


def test_flag_prefix_becomes_an_icon(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu([MenuItem("🇩🇪 Берлин", action="app.connect-profile", target=1)])

    action = item.menu.actions()[0]
    assert action.text() == "Берлин"
    assert not action.icon().isNull()


def test_left_click_is_the_primary_action(qapp):
    item = QtTrayItem(available=lambda: True)
    clicks = []
    item.set_on_primary(lambda: clicks.append(1))

    item._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    item._on_activated(QSystemTrayIcon.ActivationReason.Context)

    assert clicks == [1]


def test_publish_refuses_without_a_tray(qapp):
    item = QtTrayItem(available=lambda: False)

    with pytest.raises(RuntimeError):
        item.publish()


def test_icons_prefer_the_windows_ico():
    path = icon_file("tenga-proxy-connected", str(icons_directory()))

    assert path.suffix == ".ico" and path.is_file()


def test_tray_controller_drives_the_qt_item(qapp, tmp_path):
    from src.core.context import AppContext

    context = AppContext(config_dir=tmp_path)
    item = QtTrayItem(available=lambda: True)
    activated = []
    app = type("App", (), {"activate_action": lambda _s, n, t=None: activated.append((n, t))})()
    controller = TrayController(app, context, item=item, dispatch=lambda fn, *a: fn(*a))

    controller.start()
    controller.set_state(ConnectionState.CONNECTED, "Проба")
    try:
        labels = _labels(item.menu)
        assert labels[0] == "Статус: Проба"
        assert "Отключить" in labels
        item.menu.actions()[2].trigger()
        assert activated == [("disconnect", None)]
    finally:
        controller.stop()


def test_menu_of_the_real_builder_renders(qapp):
    item = QtTrayItem(available=lambda: True)

    item.set_menu(build_menu(ConnectionState.DISCONNECTED, []))

    assert _labels(item.menu)[-1] == "Выход"
```

**Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -m qt tests/test_ui_qt_tray.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ui.qt.tray'`

**Step 3: Implementation**

`src/ui/qt/icons.py`:

```python
"""Картинки Qt-интерфейса: флаги стран и логотип по состоянию.

Флаги — svg из комплекта: эмодзи-флагов в шрифтах Windows нет, а Qt рисует
svg одинаково на обеих системах.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtGui import QIcon

from src.core.config import get_asset_path
from src.ui.logic.country_flags import split_flag_prefix


@cache
def flag_icon(code: str) -> QIcon | None:
    path = get_asset_path(f"flags/{code}.svg")
    if not path.is_file():
        return None
    return QIcon(str(path))


def flagged(text: str) -> tuple[QIcon | None, str]:
    """Флаг в начале имени — иконкой, остальное — текстом.

    Без картинки для кода имя остаётся как есть, с эмодзи.
    """
    code, rest = split_flag_prefix(text)
    icon = flag_icon(code) if code else None
    if icon is None:
        return None, text
    return icon, rest
```

`src/ui/qt/tray.py`:

```python
"""Элемент трея на `QSystemTrayIcon` с интерфейсом `StatusNotifierItem`.

`TrayController` (src/ui/tray/controller.py) не знает, кто под ним: SNI на
Linux, Win32 или этот элемент. Меню строится из той же модели
`build_menu()`; сигналы Qt приходят в главном потоке, поэтому обработчики
вызываются напрямую, без `dispatch`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from src.ui.qt.icons import flagged
from src.ui.tray.dbusmenu import MenuItem

logger = logging.getLogger("tenga.ui.qt.tray")


def icon_file(icon_name: str, theme_path: str) -> Path:
    """`.ico` из `win/`, если есть, иначе svg: Qt читает оба формата везде."""
    base = Path(theme_path)
    ico = base / "win" / f"{icon_name}.ico"
    return ico if ico.is_file() else base / f"{icon_name}.svg"


class QtTrayItem:
    def __init__(
        self,
        *,
        available: Callable[[], bool] = QSystemTrayIcon.isSystemTrayAvailable,
    ) -> None:
        self._available = available
        self._icon = QSystemTrayIcon()
        self._menu = QMenu()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None

    def publish(self) -> None:
        if not self._available():
            # TrayController поймает ошибку и оставит приложение без трея:
            # тогда закрытие окна завершает программу, а не прячет её.
            raise RuntimeError("Системный трей недоступен")
        self._icon.show()

    def shutdown(self) -> None:
        self._icon.hide()

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        self._icon.setIcon(QIcon(str(icon_file(icon_name, theme_path))))

    def set_status(self, status: str) -> None:
        """Статусы — понятие StatusNotifierItem; у QSystemTrayIcon их нет."""

    def set_tooltip(self, text: str) -> None:
        self._icon.setToolTip(text)

    def set_menu(self, items: list[MenuItem]) -> None:
        self._menu.clear()
        self._fill(self._menu, items)

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        self._on_primary = handler

    def show_message(self, title: str, text: str) -> None:
        """Системное уведомление: на Windows 10 и 11 — тост."""
        self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information)

    @property
    def menu(self) -> QMenu:
        return self._menu

    def _fill(self, menu: QMenu, items: list[MenuItem]) -> None:
        for item in items:
            if not item.visible:
                continue
            if item.is_separator:
                menu.addSeparator()
                continue
            icon, label = flagged(item.label)
            if item.children:
                submenu = menu.addMenu(label)
                if icon is not None:
                    submenu.setIcon(icon)
                submenu.setEnabled(item.enabled)
                self._fill(submenu, item.children)
                continue
            action = menu.addAction(label)
            if icon is not None:
                action.setIcon(icon)
            action.setEnabled(item.enabled)
            if item.checked is not None:
                action.setCheckable(True)
                action.setChecked(item.checked)
            if item.action:
                action.triggered.connect(
                    lambda _checked=False, name=item.action, target=item.target: self._activate(
                        name, target
                    )
                )

    def _activate(self, name: str, target: int | None) -> None:
        if self._on_activate is not None:
            self._on_activate(name, target)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger and self._on_primary is not None:
            self._on_primary()
```

Замечания:
- В offscreen `QSystemTrayIcon.isSystemTrayAvailable()` — False, поэтому тесты передают `available=lambda: True`.
- Qt печатает `QObject::connect: No such signal QPlatformNativeInterface::systemTrayWindowChanged` в offscreen — это шум платформы, не ошибка.
- `.ico` читается встроенным плагином Qt и на Linux, svg — плагином `qsvg` из Essentials (проверено: `QImageReader.supportedImageFormats()` содержит `ico` и `svg`).

**Step 4: Run to verify it passes** — Expected: 9 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/icons.py src/ui/qt/tray.py tests/test_ui_qt_tray.py
git commit -m "feat(qt): элемент трея на QSystemTrayIcon с интерфейсом StatusNotifierItem"
```

---

### Task 4: Карточка состояния и тост

**Files:**
- Create: `src/ui/qt/widgets/status_card.py`
- Create: `src/ui/qt/widgets/toast.py`
- Test: `tests/test_ui_qt_widgets.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_widgets.py`:

```python
"""Карточка состояния и тост Qt-интерфейса."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from src.ui.logic.status import ConnectionState, status_view
from src.ui.qt.widgets.status_card import StatusCard, logo_pixmap
from src.ui.qt.widgets.toast import Toast

pytestmark = pytest.mark.qt


def test_card_shows_the_connected_view(qapp):
    card = StatusCard()

    card.update_view(
        status_view(
            ConnectionState.CONNECTED,
            profile_name="Проба",
            upload_bytes=1,
            download_bytes=2,
            mode="SYSTEM",
        )
    )

    assert card.title.text() == "Подключено"
    assert card.subtitle.text() == "Проба"
    assert "SYSTEM" in card.metrics.text()
    assert card.button.text() == "Отключить"
    assert card.property("state") == "status-connected"
    assert card.button.property("role") == "destructive-action"


def test_card_hides_empty_lines(qapp):
    card = StatusCard()

    card.update_view(status_view(ConnectionState.DISCONNECTED))

    assert card.subtitle.isHidden() and card.metrics.isHidden()
    assert card.button.text() == "Подключить"


def test_card_button_emits_action(qapp):
    card = StatusCard()
    clicks = []
    card.action_clicked.connect(lambda: clicks.append(1))

    card.button.click()

    assert clicks == [1]


@pytest.mark.parametrize("state", list(ConnectionState))
def test_every_state_has_a_logo(qapp, state):
    assert not logo_pixmap(status_view(state).css_class).isNull()


def test_toast_shows_text_and_runs_the_action(qapp):
    toast = Toast()
    clicked = []

    toast.show_message(
        "Маршрутизация импортирована", button="Вернуть", on_click=lambda: clicked.append(1)
    )
    assert not toast.isHidden()
    assert toast.label.text() == "Маршрутизация импортирована"
    assert not toast.button.isHidden()

    toast.button.click()

    assert clicked == [1] and toast.isHidden()


def test_toast_without_action_has_no_button(qapp):
    toast = Toast()

    toast.show_message("Отключено")

    assert toast.button.isHidden()
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.widgets.status_card'`.

**Step 3: Implementation**

`src/ui/qt/widgets/status_card.py`:

```python
"""Карточка состояния подключения: «Монолит», тексты и главная кнопка.

Всё, что показывается, приходит готовым `StatusView` из
`src/ui/logic/status.py` — тем же, что у GTK-карточки.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.config import get_asset_path
from src.ui.logic.status import StatusView

LOGO_SIZE = 48


@cache
def logo_pixmap(css_class: str) -> QPixmap:
    """«Монолит» с ядром цвета состояния: `status-connected` → monolith-connected.png."""
    state = css_class.removeprefix("status-")
    pixmap = QPixmap(str(get_asset_path(f"icons/win/monolith-{state}.png")))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        LOGO_SIZE,
        LOGO_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class StatusCard(QFrame):
    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.logo = QLabel()
        self.logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        self.title = QLabel()
        self.title.setObjectName("statusTitle")
        self.subtitle = QLabel()
        self.metrics = QLabel()
        self.metrics.setObjectName("statusMetrics")
        self.button = QPushButton()
        self.button.clicked.connect(self.action_clicked)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        for label in (self.title, self.subtitle, self.metrics):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            texts.addWidget(label)

        self._tools = QHBoxLayout()
        layout = QHBoxLayout(self)
        layout.addWidget(self.logo)
        layout.addLayout(texts, 1)
        layout.addWidget(self.button)
        layout.addLayout(self._tools)

    def add_tool(self, widget: QWidget) -> None:
        """Кнопки окна (панель мониторинга, меню) справа от главной."""
        self._tools.addWidget(widget)

    def update_view(self, view: StatusView) -> None:
        self.title.setText(view.title)
        self.subtitle.setText(view.subtitle)
        self.subtitle.setVisible(bool(view.subtitle))
        self.metrics.setText(view.metrics)
        self.metrics.setVisible(bool(view.metrics))
        self.button.setText(view.button_label)
        self.logo.setPixmap(logo_pixmap(view.css_class))
        # Свойства читает style.qss: цвет заголовка и вид кнопки по состоянию.
        self.setProperty("state", view.css_class)
        self.button.setProperty("role", view.button_class)
        for widget in (self, self.button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
```

`src/ui/qt/widgets/toast.py`:

```python
"""Короткое сообщение внизу окна, с необязательной кнопкой действия."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

TOAST_TIMEOUT_MS = 4000


class Toast(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton()
        self.button.clicked.connect(self._on_button)
        layout = QHBoxLayout(self)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._on_click: Callable[[], None] | None = None
        self.hide()

    def show_message(
        self,
        text: str,
        *,
        button: str | None = None,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        """Новое сообщение заменяет прежнее: очередь тостов тут не нужна."""
        self.label.setText(text)
        self._on_click = on_click
        self.button.setText(button or "")
        self.button.setVisible(bool(button and on_click))
        self.show()
        self.raise_()
        self._timer.start(TOAST_TIMEOUT_MS)

    def _on_button(self) -> None:
        self.hide()
        if self._on_click is not None:
            self._on_click()
```

Метод карточки называется `update_view`, а не `update`: `QWidget.update()` — перерисовка, и подмена сломала бы Qt.

**Step 4: Run to verify it passes** — Expected: 9 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/widgets tests/test_ui_qt_widgets.py
git commit -m "feat(qt): карточка состояния с «Монолитом» и тост"
```

---

### Task 5: Модель дерева серверов

**Files:**
- Create: `src/ui/qt/models.py`
- Test: `tests/test_ui_qt_models.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_models.py`:

```python
"""Модель дерева серверов Qt над строками profiles_view."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from src.ui.logic.latency import PingProgress
from src.ui.logic.profiles_view import GroupRow, ProfileRow
from src.ui.qt.models import (
    GROUP,
    PING_COLUMN,
    PROFILE,
    TYPE_COLUMN,
    ProfileTreeModel,
)

pytestmark = pytest.mark.qt


def _rows():
    return [
        GroupRow(
            group_id=1,
            title="Подписка",
            icon_name="",
            is_subscription=True,
            children=(
                ProfileRow(5, "🇩🇪 Берлин", "vless", "de.example:443", 40, True),
                ProfileRow(6, "Без флага", "trojan", "x.example:443", -1, False),
            ),
        ),
    ]


def test_groups_hold_their_profiles(qapp):
    model = ProfileTreeModel()

    model.set_rows(_rows())

    group = model.item(0, 0)
    assert group.text() == "Подписка"
    assert group.rowCount() == 2
    assert model.item(0, PING_COLUMN).text() == "2"
    assert group.child(1, 0).text() == "Без флага"
    assert group.child(1, PING_COLUMN).text() == "—"
    assert group.child(0, TYPE_COLUMN).text() == "VLESS"


def test_flag_prefix_turns_into_an_icon(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    berlin = model.item(0, 0).child(0, 0)

    assert berlin.text() == "Берлин"
    assert not berlin.icon().isNull()
    assert berlin.toolTip() == "🇩🇪 Берлин"


def test_active_profile_is_bold(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())
    group = model.item(0, 0)

    assert group.child(0, 0).font().bold()
    assert not group.child(1, 0).font().bold()


def test_targets_name_the_row(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    assert model.target(model.group_index(1)) == (GROUP, 1)
    assert model.target(model.profile_index(6)) == (PROFILE, 6)
    assert model.target(model.profile_index(99)) is None


def test_group_progress_replaces_the_count(qapp):
    model = ProfileTreeModel()
    progress = PingProgress({1: [5, 6]})
    model.set_rows(_rows(), progress)
    assert model.item(0, PING_COLUMN).text() == "0 / 2"

    progress.record(5)
    model.update_group_progress(1, progress)

    assert model.item(0, PING_COLUMN).text() == "1 / 2"


def test_rebuild_drops_old_rows(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    model.set_rows([])

    assert model.rowCount() == 0
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Имя"
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.models'`.

**Step 3: Implementation** — `src/ui/qt/models.py`:

```python
"""Модель дерева серверов над `build_profile_rows()`.

Строки собирает `src/ui/logic/profiles_view.py`, как и для GTK: отбор,
сортировка и порядок групп проверяются без Qt. Модель только раскладывает
готовые `GroupRow`/`ProfileRow` по ячейкам.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel

from src.ui.logic.latency import PingProgress
from src.ui.logic.profiles_view import GroupRow, ProfileRow, SortKey, ping_text
from src.ui.qt.icons import flagged

COLUMNS = ("Имя", "Тип", "Сервер", "Пинг")
NAME_COLUMN, TYPE_COLUMN, ADDRESS_COLUMN, PING_COLUMN = range(len(COLUMNS))

# По «Серверу» не сортируют и в GTK: колонки нет в SortKey.
SORT_KEYS = {NAME_COLUMN: SortKey.NAME, TYPE_COLUMN: SortKey.TYPE, PING_COLUMN: SortKey.PING}

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
ID_ROLE = Qt.ItemDataRole.UserRole + 2
GROUP, PROFILE = "group", "profile"


def _cell(text: str) -> QStandardItem:
    item = QStandardItem(text)
    item.setEditable(False)
    return item


def group_count_text(row: GroupRow, progress: PingProgress | None) -> str:
    """Число профилей, а во время замера группы — «готово / всего»."""
    state = progress.state(row.group_id) if progress is not None else None
    if state is None:
        return str(row.count)
    done, total = state
    return f"{done} / {total}"


class ProfileTreeModel(QStandardItemModel):
    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self._rows: list[GroupRow] = []

    def set_rows(self, rows: list[GroupRow], progress: PingProgress | None = None) -> None:
        self._rows = rows
        self.removeRows(0, self.rowCount())
        for row in rows:
            self.appendRow(self._group_items(row, progress))

    def _group_items(self, row: GroupRow, progress: PingProgress | None) -> list[QStandardItem]:
        name = _cell(row.title)
        cells = [name, _cell(""), _cell(""), _cell(group_count_text(row, progress))]
        for cell in cells:
            cell.setData(GROUP, KIND_ROLE)
            cell.setData(row.group_id, ID_ROLE)
        font = QFont(name.font())
        font.setBold(True)
        name.setFont(font)
        for child in row.children:
            name.appendRow(self._profile_items(child))
        return cells

    def _profile_items(self, row: ProfileRow) -> list[QStandardItem]:
        icon, title = flagged(row.title)
        name = _cell(title)
        name.setToolTip(row.title)
        if icon is not None:
            name.setIcon(icon)
        cells = [
            name,
            _cell(row.proxy_type.upper()),
            _cell(row.address),
            _cell(ping_text(row.latency_ms)),
        ]
        for cell in cells:
            cell.setData(PROFILE, KIND_ROLE)
            cell.setData(row.profile_id, ID_ROLE)
            if row.is_active:
                font = QFont(cell.font())
                font.setBold(True)
                cell.setFont(font)
        return cells

    def update_group_progress(self, group_id: int, progress: PingProgress | None) -> None:
        index = self.group_index(group_id)
        row = next((r for r in self._rows if r.group_id == group_id), None)
        if not index.isValid() or row is None:
            return
        self.item(index.row(), PING_COLUMN).setText(group_count_text(row, progress))

    def group_index(self, group_id: int) -> QModelIndex:
        for position in range(self.rowCount()):
            item = self.item(position, NAME_COLUMN)
            if item.data(ID_ROLE) == group_id:
                return item.index()
        return QModelIndex()

    def profile_index(self, profile_id: int) -> QModelIndex:
        for position in range(self.rowCount()):
            group = self.item(position, NAME_COLUMN)
            for child in range(group.rowCount()):
                item = group.child(child, NAME_COLUMN)
                if item.data(ID_ROLE) == profile_id:
                    return item.index()
        return QModelIndex()

    @staticmethod
    def target(index: QModelIndex) -> tuple[str, int] | None:
        """(«group» или «profile», id) строки под индексом."""
        if not index.isValid():
            return None
        return index.data(KIND_ROLE), index.data(ID_ROLE)
```

`QStandardItemModel`, а не собственный `QAbstractItemModel` (как предполагал дизайн): дерево пересобирается целиком из `build_profile_rows()` при каждом обновлении, как в GTK, и стандартной модели для этого хватает. Сортировка — не средствами Qt, а тем же `SortKey`, чтобы порядок совпадал с GTK (непроверенные профили в конце в обоих направлениях).

**Step 4: Run to verify it passes** — Expected: 6 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/models.py tests/test_ui_qt_models.py
git commit -m "feat(qt): модель дерева серверов над build_profile_rows"
```

---

### Task 6: Главное окно и Qt-приложение

Окно и приложение пишутся одной задачей: окно обращается к приложению (`controller`, `actions`, `loop`, `tray`, `activate_action`), а приложение создаёт окно.

**Files:**
- Create: `src/ui/qt/window.py`
- Create: `src/ui/qt/style.qss`
- Create: `src/ui/qt/application.py`
- Test: `tests/test_ui_qt_application.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_application.py`:

```python
"""Qt-приложение поверх AppController: окно, действия, диалоги, трей."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.connection import ConnectionResult
from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.controller import CONFIRM_DELETE, CONFIRM_URL_CHANGE
from src.ui.logic.profiles_view import SortKey
from src.ui.qt.application import NOT_YET_TEXT, QtApplication
from src.ui.qt.models import PING_COLUMN
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


class FakeService:
    """Подключение без xray: только состояние прокси, как у настоящего сервиса."""

    def __init__(self, context):
        self._context = context
        self.calls = []

    def connect(self, profile_id):
        self.calls.append(("connect", profile_id))
        self._context.proxy_state.set_running(profile_id, mode="system")
        return ConnectionResult(True)

    def disconnect(self):
        self.calls.append(("disconnect",))
        self._context.proxy_state.set_stopped()
        return ConnectionResult(True)

    def shutdown(self, thread):
        self.calls.append(("shutdown",))


class FakeTrayItem:
    def __init__(self):
        self.messages = []
        self.menu = []

    def publish(self):
        pass

    def shutdown(self):
        pass

    def set_icon(self, *_args):
        pass

    def set_status(self, _status):
        pass

    def set_tooltip(self, _text):
        pass

    def set_menu(self, items):
        self.menu = items

    def set_on_activate(self, _handler):
        pass

    def set_on_primary(self, _handler):
        pass

    def show_message(self, title, text):
        self.messages.append((title, text))


@pytest.fixture
def made(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    service = FakeService(context)
    app.set_connection_service(service)
    yield app, service
    if app.window is not None:
        app.window.detach()
        app.window.deleteLater()
    if app.current_dialog is not None:
        app.current_dialog.reject()
    process_events()


def _add_profile(app, name="Проба", group_id=None):
    bean = parse_link(LINK.replace("Проба", name))
    return app.controller.add_profile_from_bean(bean, group_id=group_id)


def _wait_connection(app):
    if app.controller.connection_thread is not None:
        app.controller.connection_thread.join(5)
    wait_until(
        lambda: app.controller.connection_thread is None or not app.controller.connection_busy()
    )
    for _ in range(5):
        process_events()


def test_activate_shows_the_window_with_profiles(made):
    app, _service = made
    entry = _add_profile(app)

    app.activate()

    window = app.window
    assert window.windowTitle() == "Veblock"
    assert window.status_card.title.text() == "Отключено"
    group = window.model.item(0, 0)
    assert group.child(0, 0).text() == entry.name


def test_double_click_connects_and_the_card_follows(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()
    index = app.window.model.profile_index(entry.id)

    app.window.tree.activated.emit(index)
    _wait_connection(app)

    assert service.calls == [("connect", entry.id)]
    wait_until(lambda: app.window.status_card.title.text() == "Подключено")
    assert app.window.status_card.subtitle.text() == entry.name
    assert app.last_toast_for_test == f"Подключено: {entry.name}"


def test_toggle_action_disconnects(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()
    app.controller.context.proxy_state.set_running(entry.id, mode="system")

    app.actions["toggle-connection"].trigger()
    _wait_connection(app)

    assert service.calls == [("disconnect",)]
    wait_until(lambda: app.window.status_card.title.text() == "Отключено")


def test_tray_targets_a_profile_by_number(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()

    app.activate_action("connect-profile", entry.id)
    _wait_connection(app)

    assert service.calls == [("connect", entry.id)]


def test_unknown_action_is_ignored(made):
    app, _service = made

    app.activate_action("no-such-action")


def test_dialog_actions_say_they_are_not_there_yet(made):
    app, _service = made
    app.activate()

    app.actions["settings"].trigger()

    assert app.last_toast_for_test == NOT_YET_TEXT


def test_restore_routing_follows_the_backup(made):
    app, _service = made

    assert not app.actions["restore-routing"].isEnabled()


def test_confirm_runs_only_on_the_accept_button(made):
    app, _service = made
    app.activate()
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_DELETE,
        "Оставить?",
        "Текст",
        lambda: confirmed.append(1),
        confirm_label="Оставить рабочие",
    )
    box = app.current_dialog
    assert isinstance(box, QMessageBox)
    labels = [button.text() for button in box.buttons()]
    assert "Оставить рабочие" in labels and "Отмена" in labels
    # Второй диалог поверх первого не открывается.
    assert app.present_dialog(QMessageBox()) is False

    box.defaultButton().click()
    process_events()
    assert confirmed == []
    assert app.current_dialog is None


def test_confirm_accept_calls_back(made):
    app, _service = made
    app.activate()
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: confirmed.append(1)
    )
    box = app.current_dialog
    accept = next(b for b in box.buttons() if b.text() == "Сменить")
    accept.click()
    process_events()

    assert confirmed == [1]


def test_toast_button_runs_its_action(made):
    app, _service = made
    app.activate()
    seen = []
    app._handlers["restore-routing"] = lambda _target: seen.append(1)

    app.controller.toast(
        "Маршрутизация импортирована", button="Вернуть", action="app.restore-routing"
    )
    app.window.toast_widget.button.click()

    assert seen == [1]


def test_search_filters_the_tree(made):
    app, _service = made
    _add_profile(app, "Альфа")
    _add_profile(app, "Бета")
    app.activate()

    app.window.search.setText("бета")

    group = app.window.model.item(0, 0)
    assert [group.child(i, 0).text() for i in range(group.rowCount())] == ["Бета"]


def test_ping_header_sorts_by_latency(made):
    app, _service = made
    fast = _add_profile(app, "Быстрый")
    slow = _add_profile(app, "Медленный")
    fast.latency_ms, slow.latency_ms = 10, 90
    app.activate()

    app.window._on_header_clicked(PING_COLUMN)
    app.window._on_header_clicked(PING_COLUMN)

    group = app.window.model.item(0, 0)
    assert app.window._sort_key is SortKey.PING
    assert [group.child(i, 0).text() for i in range(2)] == ["Медленный", "Быстрый"]


def test_collapsed_group_stays_collapsed_after_refresh(made):
    app, _service = made
    _add_profile(app)
    app.activate()
    index = app.window.model.index(0, 0)

    app.window.tree.collapse(index)
    app.window.refresh_pages()

    assert not app.window.tree.isExpanded(app.window.model.index(0, 0))


def test_selected_profile_survives_refresh(made):
    app, _service = made
    entry = _add_profile(app)
    app.activate()
    app.window.tree.setCurrentIndex(app.window.model.profile_index(entry.id))

    app.window.refresh_pages()

    assert app.window.selected_profile_id() == entry.id


def test_close_with_tray_hides_the_window(made):
    app, _service = made
    app.tray_item = FakeTrayItem()
    app.start_tray()
    app.activate()

    app.window.close()

    assert app.window.isHidden()
    assert app.context.config.window_size
    app.stop_tray()


def test_close_without_tray_quits(made, monkeypatch):
    app, _service = made
    app.activate()
    quits = []
    monkeypatch.setattr(app, "quit", lambda: quits.append(1))

    app.window.close()

    assert quits == [1]


def test_notifications_go_to_the_tray(made):
    app, _service = made
    item = FakeTrayItem()
    app.tray_item = item
    app.start_tray()

    app.controller.notify_user("Переключаюсь на запасной")

    assert item.messages == [("Veblock", "Переключаюсь на запасной")]
    app.stop_tray()


def test_tray_menu_comes_from_the_shared_model(made):
    app, _service = made
    item = FakeTrayItem()
    app.tray_item = item
    _add_profile(app)

    app.start_tray()

    assert item.menu[-1].label == "Выход"
    app.stop_tray()


def test_shutdown_stops_the_core(made):
    app, service = made
    app.activate()

    app.shutdown()

    assert ("shutdown",) in service.calls


def test_qt_frontend_imports_without_gtk():
    """На Windows GTK нет: Qt-интерфейс и контроллер не должны тянуть gi."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['gi'] = None; "
        "import src.ui.qt.application, src.ui.qt.tray, src.ui.tray.controller"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_window_uses_the_bundled_style(made):
    app, _service = made

    app.activate()

    assert "#statusCard" in app.window.styleSheet()
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.application'`.

**Step 3: Implementation**

`src/ui/qt/window.py`:

```python
"""Главное окно Qt: карточка, плашка, дерево серверов, поиск, мониторинг.

Рамку, заголовок и Snap Layouts даёт система: окно — обычный `QMainWindow`.
Окно рисует состояние и передаёт намерения приложению; решения принимает
`AppController`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.geometry import MIN_HEIGHT, MIN_WIDTH, Geometry, format_geometry, parse_geometry
from src.ui.logic.monitoring_view import monitoring_view
from src.ui.logic.profiles_view import SortKey, build_profile_rows
from src.ui.logic.status import ConnectionState, status_view
from src.ui.qt.models import (
    GROUP,
    NAME_COLUMN,
    PROFILE,
    SORT_KEYS,
    ProfileTreeModel,
)
from src.ui.qt.widgets.status_card import StatusCard
from src.ui.qt.widgets.toast import Toast

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.ui.logic.latency import PingProgress
    from src.ui.qt.application import QtApplication

logger = logging.getLogger("tenga.ui.qt.window")

# Пункты меню «☰»: имя действия приложения → подпись.
MAIN_MENU = (
    ("refresh-subscriptions", "Обновить подписки"),
    ("test-latency", "Проверить задержку"),
    ("settings", "Настройки"),
    ("shortcuts", "Сочетания клавиш"),
    ("about", "О программе"),
    ("quit", "Выход"),
)


STYLE_SHEET = Path(__file__).with_name("style.qss")


class _EmptyStatus:
    """Подстановка до появления монитора, как в GTK-окне."""

    proxy_ok = False
    vpn_ok = True
    last_check_time = 0.0
    proxy_error = ""
    vpn_error = ""


class MainWindow(QMainWindow):
    def __init__(self, app: QtApplication, context: AppContext) -> None:
        super().__init__()
        self._app = app
        self._context = context
        self._sort_key = SortKey.NAME
        self._ascending = True
        self._ping_progress: PingProgress | None = None
        self._collapsed: set[int] = set()

        self.setWindowTitle("Veblock")
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        geometry = parse_geometry(getattr(context.config, "window_size", ""))
        self.resize(geometry.width, geometry.height)
        self._start_maximized = geometry.maximized

        self._build_ui()
        # На окно, а не на приложение: остальные виджеты (диалоги, меню трея)
        # остаются в чистом системном стиле.
        self.setStyleSheet(STYLE_SHEET.read_text(encoding="utf-8"))
        for action in app.actions.values():
            # Сочетания клавиш работают, пока окно в фокусе.
            self.addAction(action)

        context.proxy_state.add_listener(self._on_proxy_state_changed)
        self.refresh_status()
        self.refresh_pages()

    # --- построение ---

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        self.status_card = StatusCard()
        self.status_card.action_clicked.connect(
            lambda: self._app.activate_action("toggle-connection")
        )
        self.monitoring_button = QToolButton()
        self.monitoring_button.setText("Мониторинг")
        self.monitoring_button.setCheckable(True)
        self.monitoring_button.setChecked(True)
        self.status_card.add_tool(self.monitoring_button)
        self.menu_button = QToolButton()
        self.menu_button.setText("☰")
        self.menu_button.setToolTip("Главное меню")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.main_menu = QMenu(self.menu_button)
        for name, label in MAIN_MENU:
            action = self._app.actions.get(name)
            if action is not None:
                entry = self.main_menu.addAction(label)
                entry.triggered.connect(action.trigger)
        self.menu_button.setMenu(self.main_menu)
        self.status_card.add_tool(self.menu_button)
        layout.addWidget(self.status_card)

        self.pending_banner = QFrame()
        self.pending_banner.setObjectName("pendingBanner")
        banner = QHBoxLayout(self.pending_banner)
        banner.addWidget(QLabel("Изменения применятся после переподключения"), 1)
        self.reconnect_button = QPushButton("Переподключить")
        self.reconnect_button.clicked.connect(lambda: self._app.controller.reconnect_current())
        banner.addWidget(self.reconnect_button)
        self.pending_banner.hide()
        layout.addWidget(self.pending_banner)

        self.model = ProfileTreeModel()
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(NAME_COLUMN, self.tree.header().ResizeMode.Stretch)
        self.tree.header().sectionClicked.connect(self._on_header_clicked)
        self.tree.activated.connect(self._on_activated)
        self.tree.collapsed.connect(lambda index: self._remember_collapsed(index, True))
        self.tree.expanded.connect(lambda index: self._remember_collapsed(index, False))
        layout.addWidget(self.tree, 1)

        self.toast_widget = Toast()
        layout.addWidget(self.toast_widget)

        bottom = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh_pages())
        bottom.addWidget(self.search, 1)
        layout.addLayout(bottom)

        self.setCentralWidget(central)
        self._build_monitoring_dock()

    def _build_monitoring_dock(self) -> None:
        self.monitoring_dock = QDockWidget("Мониторинг", self)
        self.monitoring_dock.setObjectName("monitoringDock")
        self.monitoring_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        body = QWidget()
        column = QVBoxLayout(body)
        self.monitoring_form = QFormLayout()
        column.addLayout(self.monitoring_form)
        self.last_check = QLabel()
        column.addWidget(self.last_check)
        self.check_button = QPushButton("Проверить сейчас")
        self.check_button.clicked.connect(self._on_check_now)
        column.addWidget(self.check_button)
        column.addStretch(1)
        self.monitoring_dock.setWidget(body)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.monitoring_dock)
        self.monitoring_button.toggled.connect(self.monitoring_dock.setVisible)
        self.monitoring_dock.visibilityChanged.connect(self._on_dock_visibility)

    # --- состояние ---

    def refresh_status(self) -> None:
        from src.ui.logic.settings_state import pending_settings

        self.pending_banner.setVisible(pending_settings(self._context))
        state = self._context.proxy_state
        if state.is_running:
            profile = self._context.profiles.get_profile(state.started_profile_id)
            view = status_view(
                ConnectionState.CONNECTED,
                profile_name=profile.name if profile else "",
                latency_ms=getattr(profile, "latency_ms", None) if profile else None,
                upload_bytes=state.upload_bytes,
                download_bytes=state.download_bytes,
                mode=state.started_mode.upper(),
            )
        else:
            view = status_view(ConnectionState.DISCONNECTED)
        self.status_card.update_view(view)

    def show_connecting(self, profile_name: str = "") -> None:
        self.status_card.update_view(
            status_view(ConnectionState.CONNECTING, profile_name=profile_name)
        )

    def show_error(self, message: str) -> None:
        self.status_card.update_view(status_view(ConnectionState.ERROR, error=message))

    def refresh_pages(self) -> None:
        """Пересобрать дерево, сохранив выделение и свёрнутые группы."""
        selected = self.selected_profile_id()
        store = self._context.profiles
        groups = store.groups
        state = self._context.proxy_state
        rows = build_profile_rows(
            groups,
            {group_id: store.get_profiles_in_group(group_id) for group_id in groups},
            query=self.search.text(),
            sort_key=self._sort_key,
            ascending=self._ascending,
            active_profile_id=state.started_profile_id if state.is_running else -1,
        )
        self.model.set_rows(rows, self._ping_progress)
        for position in range(self.model.rowCount()):
            index = self.model.index(position, NAME_COLUMN)
            group_id = self.model.target(index)[1]
            # Поиск раскрывает всё: совпадение в свёрнутой группе не видно.
            self.tree.setExpanded(
                index, bool(self.search.text()) or group_id not in self._collapsed
            )
        if selected is not None:
            index = self.model.profile_index(selected)
            if index.isValid():
                self.tree.setCurrentIndex(index)
        self.refresh_monitoring()

    def refresh_monitoring(self) -> None:
        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()
        state = self._context.proxy_state
        profile = (
            self._context.profiles.get_profile(state.started_profile_id)
            if state.is_running
            else None
        )
        routing = getattr(profile, "routing_settings", None) or self._context.config.routing
        vpn_settings = getattr(profile, "vpn_settings", None)
        vpn_enabled = bool(
            vpn_settings
            and getattr(vpn_settings, "enabled", False)
            and getattr(vpn_settings, "connection_name", "")
        )
        view = monitoring_view(
            status,
            routing,
            is_running=state.is_running,
            profile_found=profile is not None,
            vpn_enabled=vpn_enabled,
            vpn_is_up=vpn_enabled and status.vpn_ok,
        )
        while self.monitoring_form.rowCount():
            self.monitoring_form.removeRow(0)
        for row in (*view.connection, *view.routing):
            value = QLabel(row.value)
            value.setProperty("state", row.css_class)
            value.setWordWrap(True)
            self.monitoring_form.addRow(row.title, value)
        self.last_check.setText(f"Последняя проверка: {view.last_check}")

    # --- запросы оболочки контроллера ---

    def selected_profile_id(self) -> int | None:
        target = self.model.target(self.tree.currentIndex())
        if target is None or target[0] != PROFILE:
            return None
        return target[1]

    def set_sort(self, sort_key: SortKey, *, ascending: bool = True) -> None:
        self._sort_key = sort_key
        self._ascending = ascending
        column = next(c for c, key in SORT_KEYS.items() if key is sort_key)
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self.tree.header().setSortIndicator(column, order)
        self.refresh_pages()

    def set_ping_progress(self, progress: PingProgress | None) -> None:
        self._ping_progress = progress
        for row in range(self.model.rowCount()):
            group_id = self.model.target(self.model.index(row, NAME_COLUMN))[1]
            self.model.update_group_progress(group_id, progress)

    def update_group_progress(self, group_id: int) -> None:
        self.model.update_group_progress(group_id, self._ping_progress)

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        on_click = None
        if button and action:
            name = action.removeprefix("app.")

            def on_click() -> None:
                self._app.activate_action(name)

        self.toast_widget.show_message(text, button=button, on_click=on_click)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # --- события ---

    def _on_header_clicked(self, column: int) -> None:
        sort_key = SORT_KEYS.get(column)
        if sort_key is None:
            # По «Серверу» не сортируют: вернуть индикатор на текущую колонку.
            self.set_sort(self._sort_key, ascending=self._ascending)
            return
        ascending = not self._ascending if sort_key is self._sort_key else True
        self.set_sort(sort_key, ascending=ascending)

    def _on_activated(self, index) -> None:
        target = self.model.target(index)
        if target is not None and target[0] == PROFILE:
            self._app.controller.select_profile(target[1])

    def _remember_collapsed(self, index, collapsed: bool) -> None:
        target = self.model.target(index)
        if target is None or target[0] != GROUP or self.search.text():
            return
        if collapsed:
            self._collapsed.add(target[1])
        else:
            self._collapsed.discard(target[1])

    def _on_check_now(self) -> None:
        monitor = self._context.monitor
        if monitor is not None:
            monitor.check_now()
        self.refresh_monitoring()

    def _on_dock_visibility(self, visible: bool) -> None:
        # Свёрнутое окно прячет и панель: кнопка следит только за явным закрытием.
        if not self.isMinimized() and self.isVisible():
            self.monitoring_button.setChecked(visible)

    def _on_proxy_state_changed(self, _state) -> None:
        # Состояние меняет поток подключения; виджеты — только из главного.
        self._app.loop.dispatch(self._refresh_after_state_change)

    def _refresh_after_state_change(self) -> None:
        self.refresh_status()
        self.refresh_pages()

    # --- жизненный цикл ---

    def present(self) -> None:
        if self._start_maximized:
            self._start_maximized = False
            self.showMaximized()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """С треем окно прячется, без него закрытие завершает приложение."""
        self.save_geometry()
        if self._app.tray is not None:
            event.ignore()
            self.hide()
            return
        event.accept()
        self._app.quit()

    def detach(self) -> None:
        """Перестать слушать состояние прокси, как `MainWindow.detach()` в GTK."""
        self._context.proxy_state.remove_listener(self._on_proxy_state_changed)

    def save_geometry(self) -> None:
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        geometry = Geometry(width=size.width(), height=size.height(), maximized=self.isMaximized())
        self._context.config.window_size = format_geometry(geometry)
        try:
            self._context.save_config()
        except Exception as e:
            logger.warning("Could not persist window geometry: %s", e)
```

`src/ui/qt/style.qss`:

```css
/* Своей темы нет: цвета берутся из системной палитры (palette(...)).
   Правила только для карточки, плашки и тоста — у них нет системного вида. */

#statusCard {
    border: 1px solid palette(mid);
    border-radius: 8px;
}

#statusTitle {
    font-size: 15pt;
    font-weight: 600;
}

#statusCard[state="status-connected"] #statusTitle {
    color: #2e9d58;
}

#statusCard[state="status-error"] #statusTitle {
    color: #d13438;
}

#pendingBanner {
    background: palette(alternate-base);
    border-radius: 6px;
}

#toast {
    background: palette(tool-tip-base);
    border: 1px solid palette(mid);
    border-radius: 6px;
}
```

`src/ui/qt/application.py`:

```python
"""Qt-приложение: действия, оболочка контроллера, трей, запуск.

Оркестровка — в `AppController` (src/ui/controller.py), общем с GTK. Здесь
только то, что зависит от Qt: набор действий с сочетаниями клавиш, окно,
трей, слот диалога и `_QtShell`, через который контроллер говорит с окном.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtNetwork import QNetworkInformation
from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.config import get_asset_path
from src.ui.controller import CONFIRM_URL_CHANGE, AppController, resume_monitoring
from src.ui.logic.appearance import normalize_theme
from src.ui.logic.version import app_version
from src.ui.qt.dispatch import QtLoop
from src.ui.qt.window import MainWindow

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.qt.application")

# Сочетания клавиш — те же, что в GTK (`_ACCELS` в src/ui/application.py).
SHORTCUTS: dict[str, str] = {
    "add-profile": "Ctrl+N",
    "add-subscription": "Ctrl+Shift+N",
    "settings": "Ctrl+,",
    "refresh-subscriptions": "F5",
    "quit": "Ctrl+Q",
    "hide-window": "Ctrl+W",
    "toggle-connection": "Ctrl+Return",
    "test-latency": "Ctrl+T",
    "search": "Ctrl+F",
}

# Действия, у которых в Qt-интерфейсе ещё нет окна: диалоги приходят в
# фазе 3 (docs/plans/2026-10-28-windows-qt-frontend-design.md). Имена
# зарегистрированы, чтобы трей и сочетания не попадали в «неизвестное действие».
NOT_YET = (
    "add-profile",
    "add-profile-from-clipboard",
    "add-subscription",
    "add-group",
    "settings",
    "about",
    "shortcuts",
)
NOT_YET_TEXT = "Раздел появится в следующей сборке"


def network_available() -> bool:
    """Есть ли сеть вообще; без сведений о сети считаем, что есть.

    `Local` (сеть без интернета) — тоже сеть: так же отвечает
    `Gio.NetworkMonitor` в GTK, на который опирается failover.
    """
    info = QNetworkInformation.instance()
    if info is None:
        return True
    return info.reachability() != QNetworkInformation.Reachability.Disconnected


def apply_theme(theme: str | None) -> None:
    """Светлая или тёмная схема; в «Системной» Qt сам следит за ОС."""
    scheme = {
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }.get(normalize_theme(theme), Qt.ColorScheme.Unknown)
    QGuiApplication.styleHints().setColorScheme(scheme)


class _QtShell:
    """`Shell` контроллера поверх `QtApplication`; без окна — ничего не делает."""

    def __init__(self, app: QtApplication) -> None:
        self._app = app

    def _window(self) -> MainWindow | None:
        return self._app.window

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._app.last_toast_for_test = text
        window = self._window()
        if window is not None:
            window.toast(text, button=button, action=action)

    def notify(self, text: str) -> None:
        self._app.last_notification_for_test = text
        if self._app.tray_item is not None and self._app.tray is not None:
            self._app.tray_item.show_message("Veblock", text)

    def has_window(self) -> bool:
        return self._window() is not None

    def refresh_status(self) -> None:
        if (window := self._window()) is not None:
            window.refresh_status()

    def refresh_pages(self) -> None:
        if (window := self._window()) is not None:
            window.refresh_pages()

    def show_connecting(self, profile_name: str) -> None:
        if (window := self._window()) is not None:
            window.show_connecting(profile_name)

    def show_error(self, message: str) -> None:
        if (window := self._window()) is not None:
            window.show_error(message)

    def selected_profile_id(self) -> int | None:
        window = self._window()
        return None if window is None else window.selected_profile_id()

    def sort_by_ping(self) -> None:
        from src.ui.logic.profiles_view import SortKey

        if (window := self._window()) is not None:
            window.set_sort(SortKey.PING, ascending=True)

    def set_ping_progress(self, progress) -> None:
        if (window := self._window()) is not None:
            window.set_ping_progress(progress)

    def update_group_progress(self, group_id: int) -> None:
        if (window := self._window()) is not None:
            window.update_group_progress(group_id)

    def set_tray_state(self, state, profile_name: str) -> None:
        if self._app.tray is not None:
            self._app.tray.set_state(state, profile_name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        action = self._app.actions.get(name)
        if action is not None:
            action.setEnabled(enabled)

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None) -> None:
        if kind == CONFIRM_URL_CHANGE:
            accept, reject = "Сменить", "Оставить"
        else:
            accept, reject = confirm_label or "Удалить", "Отмена"
        box = QMessageBox(QMessageBox.Icon.Question, heading, body, parent=self._window())
        # Текст не разметка: адрес подписки приходит от провайдера.
        box.setTextFormat(Qt.TextFormat.PlainText)
        accept_button = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton(reject, QMessageBox.ButtonRole.RejectRole)
        # Enter и Escape не подтверждают: удалить или сменить можно только явно.
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)

        def finished(_result: int) -> None:
            if box.clickedButton() is accept_button:
                on_confirm()

        box.finished.connect(finished)
        self._app.present_dialog(box)

    def open_subscription_form(self, name: str, url: str) -> None:
        self.toast(NOT_YET_TEXT)

    def open_routing_import(self, rows, on_confirm) -> None:
        self.toast(NOT_YET_TEXT)


class QtApplication:
    """Приложение Qt-интерфейса; `QApplication` создаётся заранее."""

    def __init__(
        self,
        context: AppContext,
        *,
        lock=None,
        lock_path=None,
        with_tray: bool = True,
        accept_activation: bool = False,
        tray_item=None,
    ) -> None:
        self.qt = QApplication.instance()
        if self.qt is None:
            raise RuntimeError("QApplication must exist before QtApplication")
        self.context = context
        self.loop = QtLoop()
        self._lock = lock
        self._lock_path = lock_path
        self._with_tray = with_tray
        self._accept_activation = accept_activation
        self._activation = None
        self._dialog = None
        self._signal_timer: QTimer | None = None
        self.window: MainWindow | None = None
        self.tray = None
        self.tray_item = tray_item
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        self.controller = AppController(
            context,
            _QtShell(self),
            self.loop,
            network_available=network_available,
            app_version=app_version,
        )
        self.actions: dict[str, QAction] = {}
        self._handlers: dict[str, Callable[[int | None], None]] = {}
        self._register_actions()

    # --- действия ---

    def _register_actions(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "connect": lambda: self.controller.connect_selected(),
            "disconnect": lambda: self.controller.disconnect_proxy(),
            "toggle-connection": lambda: self.controller.toggle_connection(),
            "refresh-subscriptions": lambda: self.controller.refresh_subscriptions(),
            "test-latency": lambda: self.controller.test_latency(),
            "search": self._focus_search,
            "quit": self.quit,
            "hide-window": self._hide_window,
            "activate-window": self.activate,
            "restore-routing": lambda: self.controller.restore_routing(),
        }
        for name in NOT_YET:
            handlers[name] = lambda: self.controller.toast(NOT_YET_TEXT)

        for name, handler in handlers.items():
            action = QAction(name, self.qt)
            if name in SHORTCUTS:
                action.setShortcut(QKeySequence(SHORTCUTS[name]))
            action.triggered.connect(lambda _checked=False, fn=handler: fn())
            self.actions[name] = action
            self._handlers[name] = lambda _target, fn=handler: fn()
        # Профиль трей адресует числом, как строчные действия окна.
        self._handlers["connect-profile"] = lambda target: self.controller.connect_profile(
            int(target)
        )
        self.controller.sync_restore_routing()

    def activate_action(self, name: str, target=None) -> None:
        """Выполнить действие по имени; так его зовут трей и тосты."""
        handler = self._handlers.get(name)
        if handler is None:
            logger.warning("Unknown action %s", name)
            return
        handler(target)

    # --- окно и диалоги ---

    def activate(self) -> None:
        """Показать окно, создав его при первом вызове."""
        if self.window is None:
            self.window = MainWindow(self, self.context)
            self.controller.refresh_core_releases_if_due()
            self.controller.refresh_app_releases_if_due()
        self.window.present()
        resume_monitoring(self.context)

    def present_dialog(self, dialog) -> bool:
        """Один диалог за раз, как в GTK: второй не кладётся поверх первого."""
        if self._dialog is not None:
            return False
        self._dialog = dialog
        dialog.finished.connect(lambda _result, d=dialog: self._on_dialog_closed(d))
        dialog.open()
        return True

    def _on_dialog_closed(self, dialog) -> None:
        if self._dialog is dialog:
            self._dialog = None

    @property
    def current_dialog(self):
        return self._dialog

    def _hide_window(self) -> None:
        if self.window is not None:
            self.window.hide()

    def _focus_search(self) -> None:
        if self.window is not None:
            self.window.focus_search()

    # --- трей ---

    def start_tray(self) -> None:
        from src.ui.qt.tray import QtTrayItem
        from src.ui.tray.controller import TrayController

        if self.tray is not None:
            return
        if self.tray_item is None:
            self.tray_item = QtTrayItem()
        try:
            self.tray = TrayController(
                self, self.context, item=self.tray_item, dispatch=self.loop.dispatch
            )
            self.tray.start()
        except Exception as e:
            # Без трея приложение работает, а закрытие окна его завершает.
            logger.info("Tray is unavailable: %s", e)
            self.tray = None

    def stop_tray(self) -> None:
        if self.tray is not None:
            self.tray.stop()
            self.tray = None

    # --- жизненный цикл ---

    def start(self) -> None:
        """То, что GTK делает в `do_startup`: тема, failover, трей, активация."""
        apply_theme(getattr(self.context.config, "theme", None))
        self.controller.watch_monitor()
        if self._with_tray:
            self.start_tray()
        self._start_activation_server()

    def run(self, uris=()) -> int:
        # Процессное: тесты зовут `start()`, но не `run()`, и сигналы pytest
        # и выход общего QApplication им трогать незачем.
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.aboutToQuit.connect(self.shutdown)
        self._watch_signals()
        self.start()
        self.activate()
        for uri in uris:
            self.controller.import_app_link(uri)
        return self.qt.exec()

    def quit(self) -> None:
        self.qt.quit()

    def shutdown(self) -> None:
        if self.window is not None:
            self.window.save_geometry()
            self.window.detach()
        # Ядро гасится до снятия блокировки, как в GTK.
        self.controller.shutdown()
        self.stop_tray()
        if self._signal_timer is not None:
            self._signal_timer.stop()
        if self._activation is not None:
            self._activation.stop()
            self._activation = None
        if self._lock is not None:
            self._lock.release()

    def _watch_signals(self) -> None:
        """Ctrl+C в консоли: Python видит сигнал, только когда цикл Qt его отпускает."""
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        signal.signal(signal.SIGTERM, lambda *_: self.quit())
        self._signal_timer = QTimer()
        self._signal_timer.timeout.connect(lambda: None)
        self._signal_timer.start(250)

    def _start_activation_server(self) -> None:
        """Второй запуск на Windows передаёт ссылки первому через pipe."""
        if not self._accept_activation or self._lock is None or self._lock_path is None:
            return
        from src.sys.windows.activation import ActivationServer, pipe_address

        def deliver(uris: list[str]) -> None:
            self.loop.dispatch(self._open_uris, uris)

        try:
            self._activation = ActivationServer(pipe_address(str(self._lock_path)), deliver)
            self._activation.start()
        except OSError as e:
            logger.warning("Activation server did not start: %s", e)
            self._activation = None

    def _open_uris(self, uris: list[str]) -> None:
        self.activate()
        for uri in uris:
            self.controller.import_app_link(uri)

    # Делегаты для тестов и TrayController — те же имена, что у GTK-приложения.

    def connect_profile(self, profile_id: int) -> None:
        self.controller.connect_profile(profile_id)

    def set_connection_service(self, service) -> None:
        self.controller.set_connection_service(service)

    def set_release_fetcher(self, fetch) -> None:
        self.controller.set_release_fetcher(fetch)

    def set_app_release_fetcher(self, fetcher) -> None:
        self.controller.set_app_release_fetcher(fetcher)


def run_app(
    config_dir=None,
    lock=None,
    with_tray: bool = True,
    uris=(),
    lock_path=None,
    accept_activation: bool = False,
) -> int:
    """Точка входа Qt-интерфейса; сигнатура как у GTK-шного `run_app`."""
    from src.core.app_update import fetch_app_releases
    from src.core.context import init_context
    from src.core.core_update import fetch_releases
    from src.core.monitor import attach_monitor
    from src.sub.route import local_proxy_url

    qt = QApplication.instance() or QApplication(["tenga-proxy"])
    qt.setApplicationName("Veblock")
    qt.setDesktopFileName("tenga-proxy")
    qt.setWindowIcon(QIcon(str(get_asset_path("tenga-proxy.ico"))))
    QNetworkInformation.loadDefaultBackend()

    context = init_context(config_dir=config_dir)
    app = QtApplication(
        context,
        lock=lock,
        lock_path=lock_path,
        with_tray=with_tray,
        accept_activation=accept_activation,
    )
    # Монитор на цикле Qt: таймеры и доставка результатов проверок.
    attach_monitor(context, loop=app.loop)
    app.set_release_fetcher(fetch_releases)
    app.set_app_release_fetcher(
        lambda: fetch_app_releases(lambda: local_proxy_url(context.config, context.proxy_state))
    )
    return app.run(uris)
```

Ключевые решения в коде:
- `QtApplication` — не подкласс `QApplication`: тестам нужен один `QApplication` на процесс и новое приложение на каждый тест (как `reset_for_tests` в GTK, только без сброса).
- `run()` ставит обработчики SIGINT/SIGTERM, `aboutToQuit` и `setQuitOnLastWindowClosed(False)`; `start()` — только тему, failover, трей и активацию. Тесты зовут `start_tray()`/`activate()`, но не `run()`: сигналы pytest и общий `QApplication` им трогать незачем.
- Таймер в 250 мс в `_watch_signals` пустой: Python обрабатывает сигналы только между байткодами, а цикл Qt без него держит управление в C++.
- `network_available()` — только `Disconnected` значит «сети нет», как `Gio.NetworkMonitor.get_network_available()`.
- `app_version` передаётся контроллеру напрямую: подмену модуля, как в GTK-тестах, Qt-тесты не делают.

**Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -m qt tests/test_ui_qt_application.py -q --no-cov -p no:cacheprovider`
Expected: 21 passed.

**Step 5: Проверить компоновку глазами.** Снимок окна в offscreen:

```bash
SHOT="$(mktemp -d)"
cat > "$SHOT/shot.py" <<'PY'
import sys, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.qt.application import QtApplication
ctx = AppContext(config_dir=Path(tempfile.mkdtemp())); ctx.config
qa = QtApplication(ctx, with_tray=False)
g = qa.controller.add_group("Мои серверы")
for i, n in enumerate(["🇩🇪 Берлин", "🇳🇱 Амстердам", "🇫🇮 Хельсинки"]):
    e = qa.controller.add_profile_from_bean(parse_link(
        f"vless://11111111-2222-3333-4444-555555555555@s{i}.example.org:443?type=tcp#{n}"), group_id=g.id)
    e.latency_ms = [42, 87, -1][i]
qa.activate()
ctx.proxy_state.set_running(e.id - 2, mode="system")
qa.window.refresh_status(); qa.window.refresh_pages()
qa.controller.toast("Подключено: Берлин")
qa.window.resize(900, 560)
for _ in range(40): app.processEvents()
qa.window.grab().save(sys.argv[1])
PY
QT_QPA_PLATFORM=offscreen PYTHONPATH=. uv run python "$SHOT/shot.py" "$SHOT/shot.png"
echo "$SHOT/shot.png"
```

Expected: сверху карточка «Подключено» с цветным «Монолитом», кнопками «Отключить», «Мониторинг», «☰»; в центре дерево «Мои серверы» с флагами и жирным активным профилем; справа панель «Мониторинг» с «Проверить сейчас»; внизу тост и поле поиска.

**Step 6: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/window.py src/ui/qt/style.qss src/ui/qt/application.py tests/test_ui_qt_application.py
git commit -m "feat(qt): главное окно и приложение поверх AppController"
```

---

### Task 7: `gui.py` выбирает интерфейс

**Files:**
- Modify: `gui.py`
- Test: `tests/test_gui_entrypoint.py` (новые тесты в конец; существующие не трогать)

**Step 1: Write the failing test** — в конец `tests/test_gui_entrypoint.py`:

```python
# --- выбор интерфейса ---


def test_ui_flag_selects_the_frontend(entry):
    args, _ = entry.parse_args(["--ui", "qt"])

    assert entry.choose_frontend(args.ui) == "qt"


@pytest.mark.parametrize(("is_windows", "expected"), [(True, "qt"), (False, "gtk")])
def test_default_frontend_follows_the_os(entry, monkeypatch, is_windows, expected):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", is_windows)

    assert entry.choose_frontend(None) == expected


def test_qt_hint_names_the_dependency_group(entry):
    assert "--extra windows" in entry.install_hint("qt")
    assert entry.install_hint("gtk") == entry.gtk_install_hint()
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gui_entrypoint.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `AttributeError: ... has no attribute 'choose_frontend'`; флаг `--ui` пока попадает в неразобранные аргументы.

**Step 3: Implementation** — применить к `gui.py`:

```diff
diff --git a/gui.py b/gui.py
index bb9a9ec..22247e0 100755
--- a/gui.py
+++ b/gui.py
@@ -34,6 +34,11 @@ def build_parser() -> argparse.ArgumentParser:
     )
     parser.add_argument("uris", nargs="*", help="Ссылки импорта приложения")
     parser.add_argument("--no-tray", action="store_true", help="Не показывать иконку в трее")
+    parser.add_argument(
+        "--ui",
+        choices=("gtk", "qt"),
+        help="Интерфейс: по умолчанию Qt на Windows и GTK на Linux",
+    )
     parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
     return parser
 
@@ -52,6 +57,23 @@ def adwaita_is_supported(major: int, minor: int) -> bool:
     return (major, minor) >= MIN_ADWAITA
 
 
+def choose_frontend(requested: str | None) -> str:
+    """Qt на Windows, GTK на Linux; `--ui` переопределяет для разработки."""
+    if requested:
+        return requested
+    from src.core import platform_info
+
+    return "qt" if platform_info.IS_WINDOWS else "gtk"
+
+
+def qt_install_hint() -> str:
+    return "Установите зависимости интерфейса Qt: uv sync --extra windows"
+
+
+def install_hint(frontend: str) -> str:
+    return qt_install_hint() if frontend == "qt" else gtk_install_hint()
+
+
 def gtk_install_hint() -> str:
     from src.core import platform_info
 
@@ -101,6 +123,8 @@ def cleanup_legacy_install() -> None:
 
 
 # --- GTK bootstrap ---
+# Маркер читает tests/test_gui_entrypoint.py: выше него — только определения,
+# ниже — запуск: логи, разбор аргументов и, для GTK, проверка библиотек.
 
 logger = setup_early_logging()
 logger.info("=== Veblock starting ===")
@@ -110,6 +134,8 @@ logger.info(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
 logger.info(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE')}")
 
 _ARGS, _EXTRA = parse_args()
+FRONTEND = choose_frontend(_ARGS.ui)
+logger.info(f"Frontend: {FRONTEND}")
 
 # Локаль выбирается до импорта GTK: переводы подхватываются при инициализации
 # библиотеки, и позже смена переменных уже ничего не даёт.
@@ -117,52 +143,59 @@ from src.ui.logic.locale import apply_locale
 
 apply_locale()
 
-if "GI_TYPELIB_PATH" not in os.environ:
-    typelib_paths = [
-        "/usr/lib/girepository-1.0",
-        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
-    ]
-    existing_paths = [p for p in typelib_paths if os.path.exists(p)]
-    if existing_paths:
-        os.environ["GI_TYPELIB_PATH"] = ":".join(existing_paths)
-
-try:
-    import gi
-
-    gi.require_version("Gdk", "4.0")
-    gi.require_version("Gtk", "4.0")
-    gi.require_version("Adw", "1")
-    from gi.repository import Adw, Gdk, Gtk
-
-    if not adwaita_is_supported(Adw.MAJOR_VERSION, Adw.MINOR_VERSION):
-        print(
-            f"Нужна libadwaita {MIN_ADWAITA[0]}.{MIN_ADWAITA[1]} или новее, "
-            f"установлена {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
-        )
-        print(gtk_install_hint())
-        sys.exit(1)
 
-    logger.info("GTK4 imported successfully")
+def bootstrap_gtk() -> None:
+    """Проверить GTK и дисплей до создания приложения; Qt этого не требует."""
+    if "GI_TYPELIB_PATH" not in os.environ:
+        typelib_paths = [
+            "/usr/lib/girepository-1.0",
+            "/usr/lib/x86_64-linux-gnu/girepository-1.0",
+        ]
+        existing_paths = [p for p in typelib_paths if os.path.exists(p)]
+        if existing_paths:
+            os.environ["GI_TYPELIB_PATH"] = ":".join(existing_paths)
+
+    try:
+        import gi
+
+        gi.require_version("Gdk", "4.0")
+        gi.require_version("Gtk", "4.0")
+        gi.require_version("Adw", "1")
+        from gi.repository import Adw, Gdk, Gtk
+
+        if not adwaita_is_supported(Adw.MAJOR_VERSION, Adw.MINOR_VERSION):
+            print(
+                f"Нужна libadwaita {MIN_ADWAITA[0]}.{MIN_ADWAITA[1]} или новее, "
+                f"установлена {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
+            )
+            print(gtk_install_hint())
+            sys.exit(1)
+
+        logger.info("GTK4 imported successfully")
+
+        if not Gtk.init_check():
+            logger.error("Gtk.init_check() failed")
+            display = Gdk.Display.get_default()
+            logger.error(f"Display: {display}")
+            print("Не удалось подключиться к дисплею.")
+            print("Убедитесь, что запускаете приложение в графическом окружении.")
+            sys.exit(1)
 
-    if not Gtk.init_check():
-        logger.error("Gtk.init_check() failed")
         display = Gdk.Display.get_default()
-        logger.error(f"Display: {display}")
-        print("Не удалось подключиться к дисплею.")
-        print("Убедитесь, что запускаете приложение в графическом окружении.")
+        logger.info(f"Display: {display.get_name() if display else 'None'}")
+
+    except ImportError as e:
+        logger.exception(f"Error importing GTK: {e}")
+        print(f"Ошибка импорта GTK: {e}")
+        print(gtk_install_hint())
         sys.exit(1)
+    except Exception as e:
+        logger.exception(f"Error initializing GTK: {e}")
+        raise
 
-    display = Gdk.Display.get_default()
-    logger.info(f"Display: {display.get_name() if display else 'None'}")
 
-except ImportError as e:
-    logger.exception(f"Error importing GTK: {e}")
-    print(f"Ошибка импорта GTK: {e}")
-    print(gtk_install_hint())
-    sys.exit(1)
-except Exception as e:
-    logger.exception(f"Error initializing GTK: {e}")
-    raise
+if FRONTEND == "gtk":
+    bootstrap_gtk()
 
 from src.core.config import (
     BUNDLE_DIR,
@@ -186,15 +219,21 @@ def main() -> int:
     lock_file = get_lock_file(args.config_dir)
     single_instance = SingleInstance(lock_file)
     holds_lock = single_instance.acquire()
-    if not holds_lock:
-        from src.core.platform_info import IS_WINDOWS
+    from src.core.platform_info import IS_WINDOWS
 
+    if not holds_lock:
         if IS_WINDOWS:
             # Без D-Bus Gio.Application не найдёт первый экземпляр сам.
             from src.sys.windows.activation import pipe_address, send_activation
 
             delivered = send_activation(pipe_address(str(lock_file)), args.uris)
             return 0 if delivered else 1
+        if FRONTEND == "qt":
+            # Qt на Linux — режим разработки: окно первого экземпляра поднять
+            # некому, GApplication и D-Bus тут нет.
+            logger.info("Another instance holds the lock")
+            print("Veblock уже запущен")
+            return 1
         # Приложение всё равно запускается: имя на шине занято первым
         # процессом, он получит `activate` и поднимет окно, а этот процесс
         # сразу завершится. Блокировку он не трогает — xray остаётся один.
@@ -205,18 +244,23 @@ def main() -> int:
         cleanup_legacy_install()
 
     try:
+        options = {
+            "config_dir": args.config_dir,
+            "lock": single_instance if holds_lock else None,
+            "lock_path": lock_file,
+            "with_tray": not args.no_tray,
+            "uris": args.uris,
+        }
+        if FRONTEND == "qt":
+            from src.ui.qt.application import run_app
+
+            return run_app(**options, accept_activation=IS_WINDOWS)
         from src.ui.application import run_app
 
-        return run_app(
-            config_dir=args.config_dir,
-            lock=single_instance if holds_lock else None,
-            lock_path=lock_file,
-            with_tray=not args.no_tray,
-            uris=args.uris,
-        )
+        return run_app(**options)
     except ImportError as e:
         print(f"Ошибка импорта: {e}")
-        print(gtk_install_hint())
+        print(install_hint(FRONTEND))
         return 1
     except Exception as e:
         print(f"Ошибка: {e}")
```

Суть правки: `--ui {gtk,qt}`; `choose_frontend()` (Qt на Windows, GTK на Linux); проверка GTK и дисплея переезжает в функцию `bootstrap_gtk()` и вызывается только для GTK — на Windows `gi` больше нет; `main()` импортирует `run_app` выбранного интерфейса и передаёт Qt `accept_activation=IS_WINDOWS` (pipe активации только на Windows). Маркер `# --- GTK bootstrap ---` остаётся на месте: по нему тест отделяет определения от запуска.

**Step 4: Run to verify it passes**

```bash
uv run pytest tests/test_gui_entrypoint.py -q --no-cov -p no:cacheprovider
```

Expected: все тесты файла зелёные, включая прежние.

**Step 5: Запуск Qt на Linux без дисплея** (смоук, без подключения):

```bash
CFG="$(mktemp -d)"
QT_QPA_PLATFORM=offscreen TENGA_CONFIG_DIR="$CFG" timeout -s INT 6 uv run python gui.py --ui qt --no-tray
grep -E "Frontend|Lock released|WARNING|ERROR|Traceback" "$CFG/logs/tenga_gui.log"
```

Expected: `timeout` вернёт 124 (сработал по времени), в журнале `Frontend: qt`, в конце `Lock released`, ни `WARNING`, ни `ERROR`, ни `Traceback`. И GTK по-прежнему по умолчанию: `make test-gtk` зелёный.

**Step 6: Commit**

```bash
python cli.py lint-all
git add gui.py tests/test_gui_entrypoint.py
git commit -m "feat: gui.py выбирает интерфейс — Qt на Windows, GTK на Linux, --ui для разработки"
```

---

### Task 8: `make test-qt` и шаг CI Linux

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/linux.yml`

**Step 1:** `Makefile`:

```diff
diff --git a/Makefile b/Makefile
index 13bd718..6b7c99f 100644
--- a/Makefile
+++ b/Makefile
@@ -1,4 +1,4 @@
-.PHONY: install dev-install run cli gui test test-gtk test-tray lint format lint-all setup build install-app uninstall-app setup-dev bump-version clean clean-logs
+.PHONY: install dev-install run cli gui test test-gtk test-tray test-qt lint format lint-all setup build install-app uninstall-app setup-dev bump-version clean clean-logs
 
 # Переменные
 PYTHON := uv run python
@@ -118,6 +118,13 @@ TRAY_TESTS := $(wildcard tests/test_ui_tray_*.py)
 test-tray:
 	uv run pytest -m "" $(TRAY_TESTS) -p no:cacheprovider --no-cov
 
+# Тесты Qt-интерфейса (Windows): без дисплея, платформа offscreen. PySide6 —
+# из группы windows; без неё тесты пропускаются, а не падают.
+QT_TESTS := $(wildcard tests/test_ui_qt_*.py)
+
+test-qt:
+	QT_QPA_PLATFORM=offscreen uv run --extra windows --extra dev pytest -m qt $(QT_TESTS) -p no:cacheprovider --no-cov
+
 # Utilities
 clean:
 	rm -rf build/
```

**Step 2:** `.github/workflows/linux.yml`, задача `test`, после шага «Tray tests»:

```yaml
      # Qt-интерфейс Windows: платформа offscreen, без дисплея. Библиотеки —
      # то, что грузят платформенный плагин и QtGui из PySide6.
      - name: Qt tests
        run: |
          sudo apt-get install -y --no-install-recommends libegl1 libgl1 libfontconfig1 libxkbcommon0 libdbus-1-3
          make test-qt
```

**Step 3:** Проверить локально:

```bash
make test-qt 2>&1 | tail -1
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -1
```

Expected: `50 passed`; обычный прогон — на 4 теста больше, чем в задаче 0 (тесты точки входа), Qt-тесты в нём `deselected`.

Список apt-пакетов проверяется первым прогоном CI: если плагин offscreen не загрузится, ошибка Qt назовёт недостающую библиотеку (`libxcb-*` для offscreen не нужны).

**Step 4: Commit**

```bash
git add Makefile .github/workflows/linux.yml
git commit -m "ci: тесты Qt-интерфейса — make test-qt и шаг в linux.yml"
```

---

### Task 9: `install_dev.sh` вне MSYS2

Для проверки на VM нужен запуск из исходников обычным Python: Git Bash, CPython с python.org, uv. MSYS2 UCRT64 продолжает работать по-старому — на нём ещё стоит `windows.yml` до фазы 4.

**Files:**
- Modify: `core/scripts/install_dev.sh`

**Step 1:** Применить:

```diff
diff --git a/core/scripts/install_dev.sh b/core/scripts/install_dev.sh
index 55a636e..2ac68c3 100755
--- a/core/scripts/install_dev.sh
+++ b/core/scripts/install_dev.sh
@@ -17,6 +17,13 @@ case "$(uname -s)" in
     *) XRAY_OS="linux"; XRAY_BIN="xray" ;;
 esac
 
+# Windows: оболочка MSYS2 UCRT64 — прежняя GTK-сборка (уходит вместе с ней),
+# любая другая (Git Bash) — интерфейс Qt на обычном Python и uv.
+WINDOWS_MSYS2=0
+if [ "$XRAY_OS" = "windows" ] && [ "${MSYSTEM:-}" = "UCRT64" ]; then
+    WINDOWS_MSYS2=1
+fi
+
 SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
 PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
 cd "$PROJECT_ROOT"
@@ -89,10 +96,11 @@ check_os() {
             exit 1
             ;;
         MINGW*|MSYS*|CYGWIN*)
-            if [ "${MSYSTEM:-}" != "UCRT64" ]; then
-                warning "Ожидается оболочка MSYS2 UCRT64, сейчас: ${MSYSTEM:-не MSYS2}"
+            if [ "$WINDOWS_MSYS2" = "1" ]; then
+                success "Система: Windows (MSYS2 UCRT64, интерфейс GTK)"
+            else
+                success "Система: Windows (${MSYSTEM:-bash}, интерфейс Qt)"
             fi
-            success "Система: Windows (MSYS2 ${MSYSTEM:-})"
             return 0
             ;;
         *)
@@ -148,7 +156,8 @@ from gi.repository import Gtk, Adw; import requests" 2>/dev/null; then
 # System deps
 install_system_deps() {
     if [ "$XRAY_OS" = "windows" ]; then
-        install_windows_deps
+        # Вне MSYS2 системных пакетов нет: Python с python.org и uv.
+        [ "$WINDOWS_MSYS2" = "1" ] && install_windows_deps
         return 0
     fi
     info "Проверка системных зависимостей..."
@@ -220,7 +229,7 @@ install_system_deps() {
 }
 
 install_python_deps() {
-    if [ "$XRAY_OS" = "windows" ]; then
+    if [ "$WINDOWS_MSYS2" = "1" ]; then
         # uv поставил бы PyGObject из PyPI, а его колесо без GTK не работает.
         info "Python-зависимости на Windows приходят пакетами MSYS2, uv не нужен"
         return 0
@@ -232,6 +241,12 @@ install_python_deps() {
         exit 1
     fi
 
+    if [ "$XRAY_OS" = "windows" ] && ! check_command uv; then
+        error "uv не найден. Установите в PowerShell:"
+        error "  powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\""
+        exit 1
+    fi
+
     if ! check_command uv; then
         info "uv не найден, устанавливаем..."
         if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
@@ -248,8 +263,13 @@ install_python_deps() {
     fi
 
     info "Установка зависимостей через uv..."
-    
-    if ! uv sync; then
+
+    # На Windows интерфейс — PySide6 из группы windows; GTK там не ставится.
+    local extras=()
+    if [ "$XRAY_OS" = "windows" ]; then
+        extras=(--extra windows --extra dev)
+    fi
+    if ! uv sync "${extras[@]}"; then
         error "Не удалось установить зависимости через uv"
         exit 1
     fi
@@ -273,6 +293,25 @@ check_xray() {
     return 1
 }
 
+# Распаковать архив, не трогая существующие файлы (unzip -n). В Git Bash
+# unzip нет — тот же отбор делает Python из окружения проекта.
+extract_new() {
+    if check_command unzip; then
+        unzip -q -n "$1"
+        return
+    fi
+    uv run --no-sync python - "$1" <<'PY'
+import os
+import sys
+import zipfile
+
+with zipfile.ZipFile(sys.argv[1]) as archive:
+    for member in archive.infolist():
+        if not os.path.exists(member.filename):
+            archive.extract(member)
+PY
+}
+
 download_xray() {
     if check_xray; then
         success "xray-core найден"
@@ -330,7 +369,7 @@ download_xray() {
     fi
 
     # -n: геобазы в core/bin лежат в git, архив их не перезаписывает.
-    if ! unzip -q -n xray.zip; then
+    if ! extract_new xray.zip; then
         error "Ошибка при распаковке архива"
         rm -f xray.zip
         cd "$PROJECT_ROOT"
```

Что меняется: `WINDOWS_MSYS2=1` только в оболочке UCRT64; вне неё системные пакеты не ставятся, Python-зависимости — `uv sync --extra windows --extra dev`; без uv скрипт называет команду установки для PowerShell; архив xray распаковывается `extract_new` — `unzip -n`, а где его нет (Git Bash), тот же отбор делает Python.

**Step 2:** Проверить синтаксис и распаковку без `unzip`:

```bash
bash -n core/scripts/install_dev.sh && echo ok
cd "$(mktemp -d)" && python3 -c "import zipfile; z=zipfile.ZipFile('x.zip','w'); z.writestr('a.txt','new'); z.writestr('b.txt','new'); z.close()" \
  && echo old > a.txt \
  && bash -c "check_command(){ return 1; }; uv(){ shift 3; python3 \"\$@\"; }; $(sed -n '/^extract_new() {/,/^}/p' "$OLDPWD/core/scripts/install_dev.sh"); extract_new x.zip" \
  && cat a.txt b.txt; cd "$OLDPWD"
```

Expected: `ok`, затем `old` и `new` — существующий файл не перезаписан, новый распакован.

**Step 3: Commit**

```bash
git add core/scripts/install_dev.sh
git commit -m "build: install_dev.sh на Windows вне MSYS2 — uv и интерфейс Qt"
```

---

### Task 10: Документация

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `docs/ru/development.md`, `docs/en/development.md`
- Modify: `docs/plans/2026-10-28-windows-qt-frontend-design.md`
- Modify: этот план (раздел «Статус»)

**Step 1:** `CLAUDE.md`:
- в дерево «Project Structure» после строки `controller.py` добавить
  `│   ├── qt/            # Интерфейс PySide6 (Windows; на Linux — gui.py --ui qt)`;
- в «Running» после `python gui.py`:
  ```bash
  # Qt-интерфейс на Linux (нужна группа windows: uv sync --extra windows)
  python gui.py --ui qt
  ```
- в «Testing» после блока про `make test-tray`:
  ```markdown
  - Тесты Qt-интерфейса — `make test-qt`: маркер `qt`, платформа offscreen,
    PySide6 из группы `windows`. pytest-qt не используется: без PySide6 его
    плагин роняет весь pytest. Фикстура `qapp` — в `tests/conftest.py`,
    ожидание событий — `tests/support/qt.py`
  ```
- блок **GUI Architecture** дополнить абзацем:
  ```markdown
  **Qt-интерфейс** (`src/ui/qt/`) — на Windows по умолчанию, на Linux по
  `--ui qt`. `QtApplication` — оболочка над тем же `AppController`:
  `QAction` с именами действий GTK, `_QtShell`, `QtLoop` (главный цикл Qt
  как `MainLoop`), `QtTrayItem` для `TrayController`. Выбор интерфейса —
  `choose_frontend()` в `gui.py`; модули `src/ui/qt` не импортируют `gi`
  и не читают `IS_WINDOWS`
  ```
- в «Important Notes → Testing» строку про Windows-разработку заменить на:
  ```markdown
  - Windows-разработка — Git Bash, CPython с python.org и uv
    (`bash core/scripts/install_dev.sh` ставит `--extra windows --extra dev`).
    MSYS2 UCRT64 нужна только прежней GTK-сборке и CI до фазы 4
    (`docs/plans/2026-10-28-windows-qt-frontend-design.md`)
  ```

**Step 2:** `AGENTS.md`, «Карта исходников», после строки про `src/ui/controller.py`:

```markdown
- `src/ui/qt/` — интерфейс PySide6 (Windows; на Linux — `gui.py --ui qt`).
```

**Step 3:** `docs/ru/development.md` после раздела «Контроллер приложения»:

```markdown
### Интерфейс Qt

`src/ui/qt/` — интерфейс Windows на PySide6. На Linux он запускается
`python gui.py --ui qt` после `uv sync --extra windows`. Тесты —
`make test-qt` (платформа offscreen, дисплей не нужен).

На Windows окружение разработки — Git Bash, Python 3.12 с python.org и uv:
`bash core/scripts/install_dev.sh`, затем `uv run python gui.py`.
```

`docs/en/development.md` после «Application Controller»:

```markdown
### Qt Interface

`src/ui/qt/` is the PySide6 interface for Windows. On Linux, run it with
`python gui.py --ui qt` after `uv sync --extra windows`. Tests:
`make test-qt` (offscreen platform, no display needed).

On Windows, develop in Git Bash with Python 3.12 from python.org and uv:
`bash core/scripts/install_dev.sh`, then `uv run python gui.py`.
```

**Step 4:** Дизайн-документ, раздел «Сборка и поставка»: строку «в `dev` добавляется `pytest-qt`» заменить на «pytest-qt не используется (без PySide6 его плагин роняет pytest); `qapp` — своя фикстура»; в пункте про spec убрать `PySide6.QtNetwork` из исключаемых и дописать «QtNetwork нужен `QNetworkInformation` для failover». В разделе «Тестирование» `pytest-qt` заменить на «фикстура `qapp` и `tests/support/qt.py`».

**Step 5:** В конец этого плана — раздел «Статус» с датой, числами тестов до/после и отклонениями.

**Step 6: Commit**

```bash
python cli.py lint-all
uv run pytest -q --no-cov -p no:cacheprovider
git add CLAUDE.md AGENTS.md docs/
git commit -m "docs: Qt-интерфейс, make test-qt, разработка на Windows без MSYS2"
```

---

### Task 11: Проверка на Linux и на VM Windows 10 и 11

Проверка руками; результат — в раздел «Статус».

**Linux (машина разработчика, режим системного прокси, не TUN):**

1. `uv sync --extra windows`, `python gui.py --ui qt`.
2. Окно открывается с геометрией из настроек; профили в дереве, флаги картинками.
3. Двойной клик по профилю — «Подключение…», затем «Подключено» и метрики; трей меняет иконку.
4. «Отключить» на карточке и «Отключить» в меню трея.
5. Ctrl+F — фокус в поиске; F5 — обновление подписок; Ctrl+T — замер, прогресс «готово / всего» у групп.
6. Клик по «Пинг» — сортировка по задержке, повторный — обратная.
7. Закрытие окна — окно прячется в трей; «Открыть окно» из трея; «Выход» — процесс завершается, ядро остановлено.
8. Второй запуск `python gui.py --ui qt` — «Veblock уже запущен».

**VM Windows 10 и Windows 11 (из исходников):**

1. Git для Windows, Python 3.12 с python.org (галочка «Add to PATH»), uv:
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. Git Bash: `git clone …`, `cd tenga-proxy`, `bash core/scripts/install_dev.sh` — xray.exe и wintun.dll в `core/bin`, `uv sync --extra windows --extra dev`.
3. `uv run python gui.py` — Qt-интерфейс без флагов; стиль `windows11` на 11 и `windowsvista` на 10 (`QApplication.style().name()` в журнале не пишется — смотреть глазами: кнопки и полосы прокрутки системные).
4. Snap Layouts при наведении на «развернуть» (Windows 11); тёмная тема системы — окно тёмное (тема «Система»).
5. Трей: иконка «Монолита», левый клик — окно, правый — меню с флагами; DPI 125 % и 150 % — флаги в меню и дереве не размыты (открытый вопрос дизайна).
6. Подключение в режиме системного прокси, отключение. TUN — только если служба `TengaProxySvc` установлена; в этой фазе её ставит прежний установщик, проверка TUN откладывается до фазы 4.
7. Уведомление: включить автопереключение, оборвать соединение — тост Windows (на 10 возможна всплывашка трея: открытый вопрос про AppUserModelID).
8. Второй запуск `uv run python gui.py veblock://add/...` — ссылка доходит до первого экземпляра (pipe активации), показывается тост «Раздел появится в следующей сборке» (формы — фаза 3).
9. Перезапуск Проводника (`taskkill /f /im explorer.exe`, `start explorer`) — иконка трея возвращается (открытый вопрос дизайна).

---

## Что намеренно не делается в этой фазе

- Диалоги (профиль, подписка, группа, маршрутизация профиля, импорт маршрутизации, подтверждения кроме `QMessageBox`), окно настроек, «О программе», сочетания клавиш, контекстные меню дерева, кнопка «Добавить» — фаза 3.
- Настройка «Сворачивать в трей при закрытии», запоминание панели мониторинга, срок и трафик подписки в заголовке группы, флаг картинкой в карточке — фаза 3.
- PyInstaller spec, Inno Setup, `windows.yml`, удаление Win32-трея, `style-windows.css`, `assets/flags/win/*.bmp` и Windows-веток `platform_layout.py` — фаза 4.
- `TrayController._default_item()` на Windows по-прежнему выбирает Win32-элемент: его зовёт только GTK-приложение, Qt передаёт `QtTrayItem` явно. Удаление — фаза 4.
- AppUserModelID — по итогам проверки на VM (задача 11, пункт 7).

---

## Статус

**28.10.2026 — задачи 0–10 выполнены, задача 11 частично.**

Код взят из плана без отступлений; коммиты `ac5f183`…`b42577c` и
документация.

| Прогон | До фазы | После |
|---|---|---|
| `uv run pytest` | 1583 passed, 10 skipped | 1587 passed, 10 skipped (+4 теста точки входа) |
| `make test-gtk` | 279 passed | 279 passed |
| `make test-tray` | 146 passed, 5 skipped | 146 passed, 5 skipped |
| `make test-qt` | — | 50 passed |
| `python cli.py lint-all` | чисто | чисто |

Задача 11, сделано в offscreen на Linux:
- `gui.py --ui qt --no-tray` стартует и завершается по SIGINT: в журнале
  `Frontend: qt` и `Lock released`, предупреждений и ошибок нет;
- вторая копия `--ui qt` с тем же каталогом настроек печатает «Veblock уже
  запущен» и выходит с кодом 1;
- снимок окна совпадает с ожидаемым (карточка, дерево с флагами, мониторинг,
  тост, поиск).

Не сделано, остаётся за разработчиком:
- Linux, пункты 2–7: подключение в режиме системного прокси на живом
  дисплее. На машине разработчика работает TUN-сессия, системный прокси не
  менялся;
- проверка на VM Windows 10 и 11 целиком.
