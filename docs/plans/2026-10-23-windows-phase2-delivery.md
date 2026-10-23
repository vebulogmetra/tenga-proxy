# Фаза 2. Поставка: трей Win32, PyInstaller, установщик, CI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Контекст: `docs/plans/2026-10-23-windows-port-design.md` (разделы «Трей», «Сборка и поставка»),
> дорожная карта `docs/plans/2026-10-23-windows-port-plan.md`.
> Предыдущая фаза: `docs/plans/2026-10-23-windows-phase1-foundation.md`.

**Goal:** Установщик `tenga-proxy-<версия>-windows-x64-setup.exe`, собранный в CI, ставит приложение с иконкой в трее; установленное приложение работает в режиме системного прокси.

**Architecture:** Трей Win32 — это ещё одна реализация интерфейса `item`, который `TrayController` уже принимает (`set_icon`, `set_tooltip`, `set_menu`, `set_on_activate`, `set_on_primary`, `publish`, `shutdown`). Логика (обход дерева меню, экранирование подписей, выбор пункта, переадресация в главный цикл GLib) отделена от ctypes и тестируется на Linux; ctypes-слой — окно сообщений в своём потоке. Сборка: PyInstaller в MSYS2 UCRT64 (onedir) и Inno Setup; CI на `windows-latest` гоняет тесты и выкладывает установщик артефактом.

**Tech Stack:** ctypes (user32, shell32), PyInstaller 6 + pyinstaller-hooks-contrib (хуки `gi`), Inno Setup 6, GitHub Actions `msys2/setup-msys2@v2`, GdkPixbuf (только в инструменте генерации иконок).

---

## Принятые решения

- **Иконки `.ico` генерируются скриптом и коммитятся.** SVG трея рендерит
  GdkPixbuf (есть на машине разработчика), ICO собирается из PNG-кадров
  собственным писателем на 30 строк: формат ICO позволяет хранить PNG как есть,
  Pillow не нужен. Так сборка на Windows не зависит от рендеринга SVG.
- **Меню — нативное `TrackPopupMenu`**, а не GTK-попап: так оно выглядит и
  закрывается, как у всех программ в трее.
- **Окно трея — в отдельном потоке** со своим циклом `GetMessageW`. Все
  вызовы в приложение возвращаются в главный цикл через `GLib.idle_add`, как
  в `TrayController._default_dispatch`. Запасной вариант (если поток
  конфликтует с GTK) — в дорожной карте.
- **Установщик требует прав администратора** уже в этой фазе: Program Files,
  а в фазе 3 — регистрация службы. Конфигурация пользователя от этого не
  зависит: она в `%APPDATA%`.
- **Схемы ссылок `veblock://` и `wingeon://`** регистрируются установщиком
  в `HKCU\Software\Classes` (аналог `MimeType` в `.desktop`).
- Версия установщика берётся из `src/__init__.py` сценарием сборки, поэтому
  `cli.py bump-version` менять не нужно.

---

### Task 2.0: Сверка с кодом

**Step 1:** Убедиться, что фаза 1 выполнена: `src/core/platform_info.py`,
`src/sys/windows/` с шестью модулями, `tests/test_sys_facades.py` с
`WINDOWS_READY = FACADES`.

**Step 2:** Перечитать `src/ui/tray/controller.py`, `src/ui/tray/sni.py`
(публичные методы), `src/ui/tray/dbusmenu.py` (`MenuItem`, `MenuModel.find`),
`src/ui/tray/icons.py`. Если интерфейс `item` изменился, привести задачи 2.3–2.4
в соответствие.

**Step 3:** Прочитать раздел «Статус» фазы 1: итоги разведки на VM и ручной
приёмки. Если GTK в MSYS2 не запустился, остановиться и обсудить с владельцем.

---

### Task 2.1: Писатель ICO и иконки для Windows

**Files:**
- Create: `src/ui/tray/win32/__init__.py` (docstring)
- Create: `src/ui/tray/win32/ico.py`
- Create: `tools/make_ico.py`
- Create: `assets/icons/win/tenga-proxy-{disconnected,connecting,connected}.ico`, `assets/tenga-proxy.ico`
- Test: `tests/test_ui_tray_win32_ico.py`

**Step 1: Write the failing test**

```python
"""ICO из PNG-кадров: заголовок и каталог по спецификации."""

from __future__ import annotations

import struct

from src.ui.tray.win32.ico import build_ico

PNG_16 = b"\x89PNG\r\n\x1a\n" + b"a" * 20
PNG_256 = b"\x89PNG\r\n\x1a\n" + b"b" * 30


def test_header_counts_images():
    data = build_ico([(16, PNG_16), (256, PNG_256)])

    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, 2)


def test_directory_points_at_png_payloads():
    data = build_ico([(16, PNG_16), (256, PNG_256)])

    width, height, _colors, _res, _planes, bpp, size, offset = struct.unpack_from(
        "<BBBBHHII", data, 6
    )
    assert (width, height, bpp) == (16, 16, 32)
    assert data[offset : offset + size] == PNG_16

    width, height, *_rest, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16)
    # 256 пикселей записываются нулём: поле занимает один байт.
    assert (width, height) == (0, 0)
    assert data[offset : offset + size] == PNG_256
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_win32_ico.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/ui/tray/win32/ico.py`:

```python
"""Сборка ICO из готовых PNG-кадров.

С Windows Vista ICO может хранить кадры в PNG как есть, поэтому кодировать
пиксели не нужно: заголовок, каталог по 16 байт на кадр и сами PNG подряд.
"""

from __future__ import annotations

import struct

_HEADER = struct.Struct("<HHH")
_ENTRY = struct.Struct("<BBBBHHII")


def build_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """`frames` — пары (размер стороны, PNG-байты), размер от 1 до 256."""
    offset = _HEADER.size + _ENTRY.size * len(frames)
    directory = b""
    for size, png in frames:
        side = 0 if size >= 256 else size
        directory += _ENTRY.pack(side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return _HEADER.pack(0, 1, len(frames)) + directory + b"".join(png for _, png in frames)
```

`tools/make_ico.py`:

```python
"""Сгенерировать .ico для Windows из SVG трея и PNG приложения.

Запуск на машине разработчика (нужен GdkPixbuf с загрузчиком SVG):
    uv run python tools/make_ico.py
Результат коммитится: сборка на Windows SVG не рендерит.
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ui.tray.icons import ICON_NAMES  # noqa: E402
from src.ui.tray.win32.ico import build_ico  # noqa: E402

TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)
APP_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(pixbuf) -> bytes:
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return bytes(data)


def from_file(path: Path, sizes) -> bytes:
    frames = [
        (size, png_bytes(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)))
        for size in sizes
    ]
    return build_ico(frames)


def main() -> int:
    out_dir = ROOT / "assets" / "icons" / "win"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ICON_NAMES:
        (out_dir / f"{name}.ico").write_bytes(
            from_file(ROOT / "assets" / "icons" / f"{name}.svg", TRAY_SIZES)
        )
    app_png = ROOT / "assets" / "theme" / "hicolor" / "256x256" / "apps" / "tenga-proxy.png"
    (ROOT / "assets" / "tenga-proxy.ico").write_bytes(from_file(app_png, APP_SIZES))
    print(f"Written to {out_dir} and assets/tenga-proxy.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests and generate icons**

Run: `uv run pytest tests/test_ui_tray_win32_ico.py -v --no-cov`
Expected: 2 passed

Run: `uv run python tools/make_ico.py && file assets/icons/win/*.ico assets/tenga-proxy.ico`
Expected: `MS Windows icon resource - 7 icons` для каждого файла

**Step 5: Commit**

```bash
git add src/ui/tray/win32 tools/make_ico.py assets/icons/win assets/tenga-proxy.ico tests/test_ui_tray_win32_ico.py
git commit -m "feat(tray): иконки .ico для Windows и их генератор"
```

---

### Task 2.2: Меню трея в операции Win32

**Files:**
- Create: `src/ui/tray/win32/menu_ops.py`
- Test: `tests/test_ui_tray_win32_menu.py`

**Step 1: Write the failing test**

```python
"""Дерево меню трея → последовательность вызовов AppendMenuW."""

from __future__ import annotations

from src.ui.logic.status import ConnectionState
from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator
from src.ui.tray.menu import build_menu
from src.ui.tray.win32.menu_ops import Entry, Popup, Separator, menu_ops, win32_label


def test_ampersand_is_escaped():
    assert win32_label("Tom & Jerry") == "Tom && Jerry"


def test_flat_items_keep_model_ids_and_flags():
    model = MenuModel(
        [
            MenuItem("Статус", enabled=False),
            separator(),
            MenuItem("Подключить", action="app.connect"),
        ]
    )

    ops = menu_ops(model)

    assert ops == [
        Entry(id=1, label="Статус", enabled=False, checked=False),
        Separator(),
        Entry(id=3, label="Подключить", enabled=True, checked=False),
    ]


def test_children_become_popup():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A", checked=True)])])

    ops = menu_ops(model)

    assert ops == [Popup(label="Профили", children=[Entry(id=2, label="A", enabled=True, checked=True)])]


def test_invisible_items_are_skipped():
    model = MenuModel([MenuItem("x", visible=False), MenuItem("y")])

    assert [op.label for op in menu_ops(model)] == ["y"]


def test_real_menu_converts():
    model = MenuModel(build_menu(ConnectionState.DISCONNECTED, []))

    assert any(isinstance(op, Popup) for op in menu_ops(model))
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_win32_menu.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/ui/tray/win32/menu_ops.py`:

```python
"""Дерево `MenuModel` в виде операций для AppendMenuW.

Идентификатор пункта Win32 совпадает с id модели, поэтому выбранный пункт
находится тем же `MenuModel.find`, что и в dbusmenu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.ui.tray.dbusmenu import MenuItem, MenuModel


@dataclass(frozen=True)
class Entry:
    id: int
    label: str
    enabled: bool
    checked: bool


@dataclass(frozen=True)
class Separator:
    label: str = ""


@dataclass
class Popup:
    label: str
    children: list = field(default_factory=list)


def win32_label(text: str) -> str:
    """`&` в Win32 — признак мнемоники; буквальный амперсанд удваивается."""
    return text.replace("&", "&&")


def _convert(items: list[MenuItem]) -> list:
    ops = []
    for item in items:
        if not item.visible:
            continue
        if item.is_separator:
            ops.append(Separator())
        elif item.children:
            ops.append(Popup(label=win32_label(item.label), children=_convert(item.children)))
        else:
            ops.append(
                Entry(
                    id=item.id,
                    label=win32_label(item.label),
                    enabled=item.enabled,
                    checked=bool(item.checked),
                )
            )
    return ops


def menu_ops(model: MenuModel) -> list:
    return _convert(model.root.children)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_ui_tray_win32_menu.py -v --no-cov`
Expected: 5 passed

**Step 5: Commit**

```bash
git add src/ui/tray/win32/menu_ops.py tests/test_ui_tray_win32_menu.py
git commit -m "feat(tray): преобразование меню трея в операции Win32"
```

---

### Task 2.3: Элемент трея Win32

**Files:**
- Create: `src/ui/tray/win32/item.py` (логика, без ctypes)
- Create: `src/ui/tray/win32/backend.py` (ctypes, только Windows)
- Test: `tests/test_ui_tray_win32_item.py`

**Step 1: Write the failing tests**

```python
"""Элемент трея Win32: логика поверх подменённого окна сообщений."""

from __future__ import annotations

import pytest

from src.ui.tray.dbusmenu import MenuItem
from src.ui.tray.win32.item import Win32TrayItem


class FakeBackend:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.updates = []
        self.chosen = 0
        self.shown_ops = None
        self.on_event = None

    def start(self, on_event):
        self.started = True
        self.on_event = on_event

    def update(self, icon_path, tooltip):
        self.updates.append((icon_path, tooltip))

    def show_menu(self, ops):
        self.shown_ops = ops
        return self.chosen

    def stop(self):
        self.stopped = True


def immediate(fn, *args):
    fn(*args)


@pytest.fixture
def item(tmp_path):
    backend = FakeBackend()
    tray = Win32TrayItem(backend=backend, dispatch=immediate, icons_dir=tmp_path)
    return tray, backend


def test_publish_starts_backend(item):
    tray, backend = item

    tray.publish()

    assert backend.started


def test_icon_name_maps_to_ico_file(item, tmp_path):
    tray, backend = item
    tray.publish()

    tray.set_icon("tenga-proxy-connected", "/ignored/theme/path")

    assert backend.updates[-1][0] == str(tmp_path / "tenga-proxy-connected.ico")


def test_tooltip_is_cut_to_127_chars(item):
    tray, backend = item
    tray.publish()

    tray.set_tooltip("x" * 300)

    assert len(backend.updates[-1][1]) == 127


def test_left_click_runs_primary(item):
    tray, backend = item
    calls = []
    tray.set_on_primary(lambda: calls.append("primary"))
    tray.publish()

    backend.on_event("primary")

    assert calls == ["primary"]


def test_menu_choice_runs_action_with_target(item):
    tray, backend = item
    got = []
    tray.set_on_activate(lambda action, target: got.append((action, target)))
    tray.set_menu([MenuItem("A", action="app.connect-profile", target=5)])
    tray.publish()
    backend.chosen = 1

    backend.on_event("menu")

    assert got == [("app.connect-profile", 5)]


def test_dismissed_menu_does_nothing(item):
    tray, backend = item
    got = []
    tray.set_on_activate(lambda *a: got.append(a))
    tray.set_menu([MenuItem("A", action="app.connect")])
    tray.publish()
    backend.chosen = 0

    backend.on_event("menu")

    assert got == []


def test_shutdown_stops_backend_once(item):
    tray, backend = item
    tray.publish()

    tray.shutdown()
    tray.shutdown()

    assert backend.stopped
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_tray_win32_item.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write `item.py`**

```python
"""Элемент трея Windows с тем же интерфейсом, что у `StatusNotifierItem`.

Окно сообщений и вызовы Shell_NotifyIcon живут в `backend.py` и своём потоке;
здесь — только состояние и решения: какой файл иконки, какой пункт выбран.
События окна приходят из его потока, поэтому обработчики приложения
вызываются через `dispatch` (по умолчанию `GLib.idle_add`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from src.ui.tray.dbusmenu import MenuItem, MenuModel
from src.ui.tray.win32.menu_ops import menu_ops

logger = logging.getLogger("tenga.ui.tray.win32")

# szTip в NOTIFYICONDATAW — 128 символов с завершающим нулём.
TOOLTIP_LIMIT = 127


def _glib_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


def default_icons_dir() -> Path:
    from src.core.config import BUNDLE_DIR

    return BUNDLE_DIR / "assets" / "icons" / "win"


class Win32TrayItem:
    def __init__(self, *, backend=None, dispatch=_glib_dispatch, icons_dir: Path | None = None):
        if backend is None:
            from src.ui.tray.win32.backend import NotifyIconWindow

            backend = NotifyIconWindow()
        self._backend = backend
        self._dispatch = dispatch
        self._icons_dir = icons_dir or default_icons_dir()
        self._icon_path = ""
        self._tooltip = ""
        self._menu = MenuModel([])
        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None
        self._published = False

    def publish(self) -> None:
        self._backend.start(self._on_event)
        self._published = True
        self._push()

    def shutdown(self) -> None:
        if not self._published:
            return
        self._published = False
        self._backend.stop()

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        # theme_path нужен панелям Linux; на Windows иконка — файл .ico.
        self._icon_path = str(self._icons_dir / f"{icon_name}.ico")
        self._push()

    def set_status(self, status: str) -> None:
        """Statuses are a StatusNotifierItem notion; Windows has none."""

    def set_tooltip(self, text: str) -> None:
        self._tooltip = text[:TOOLTIP_LIMIT]
        self._push()

    def set_menu(self, items: list[MenuItem]) -> None:
        self._menu = MenuModel(items)

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        self._on_primary = handler

    def _push(self) -> None:
        if self._published:
            self._backend.update(self._icon_path, self._tooltip)

    def _on_event(self, kind: str) -> None:
        """Вызывается из потока окна."""
        if kind == "primary" and self._on_primary is not None:
            self._dispatch(self._on_primary)
        elif kind == "menu":
            chosen = self._backend.show_menu(menu_ops(self._menu))
            item = self._menu.find(chosen) if chosen else None
            if item is not None and item.action and self._on_activate is not None:
                self._dispatch(self._on_activate, item.action, item.target)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_ui_tray_win32_item.py -v --no-cov`
Expected: 7 passed

**Step 5: Write `backend.py`**

Импорты ctypes-структур — внутри модуля, но сам модуль импортируется только
на Windows (из `Win32TrayItem.__init__`). Все функции объявляются с
`argtypes`/`restype`: без этого 64-битные дескрипторы обрезаются до `int`.

```python
"""Окно сообщений Win32 с иконкой в области уведомлений.

Свой поток: RegisterClassExW → CreateWindowExW (невидимое окно верхнего уровня:
message-only окно не получает широковещательное `TaskbarCreated`) → цикл
GetMessageW. Изменения из главного потока складываются под замком и
применяются по `WM_APP_UPDATE`. После перезапуска Проводника иконка
добавляется заново по сообщению `TaskbarCreated`.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

logger = logging.getLogger("tenga.ui.tray.win32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_APP_TRAY = WM_APP + 1
WM_APP_UPDATE = WM_APP + 2

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sig = {
        user32.RegisterClassExW: ([ctypes.POINTER(WNDCLASSEXW)], wintypes.ATOM),
        user32.CreateWindowExW: (
            [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID],
            wintypes.HWND,
        ),
        user32.DefWindowProcW: (
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], LRESULT
        ),
        user32.DestroyWindow: ([wintypes.HWND], wintypes.BOOL),
        user32.PostMessageW: (
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL
        ),
        user32.GetMessageW: (
            [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT],
            wintypes.BOOL,
        ),
        user32.TranslateMessage: ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        user32.DispatchMessageW: ([ctypes.POINTER(wintypes.MSG)], LRESULT),
        user32.PostQuitMessage: ([ctypes.c_int], None),
        user32.RegisterWindowMessageW: ([wintypes.LPCWSTR], wintypes.UINT),
        user32.LoadImageW: (
            [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
             wintypes.UINT],
            wintypes.HANDLE,
        ),
        user32.DestroyIcon: ([wintypes.HICON], wintypes.BOOL),
        user32.GetSystemMetrics: ([ctypes.c_int], ctypes.c_int),
        user32.CreatePopupMenu: ([], wintypes.HMENU),
        user32.AppendMenuW: (
            [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR], wintypes.BOOL
        ),
        user32.DestroyMenu: ([wintypes.HMENU], wintypes.BOOL),
        user32.TrackPopupMenu: (
            [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             wintypes.HWND, wintypes.LPVOID],
            wintypes.BOOL,
        ),
        user32.GetCursorPos: ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        user32.SetForegroundWindow: ([wintypes.HWND], wintypes.BOOL),
        shell32.Shell_NotifyIconW: (
            [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)], wintypes.BOOL
        ),
        kernel32.GetModuleHandleW: ([wintypes.LPCWSTR], wintypes.HMODULE),
    }
    for fn, (argtypes, restype) in sig.items():
        fn.argtypes = argtypes
        fn.restype = restype
    return user32, shell32, kernel32


class NotifyIconWindow:
    CLASS_NAME = "TengaProxyTrayWindow"

    def __init__(self):
        self._user32, self._shell32, self._kernel32 = _api()
        self._lock = threading.Lock()
        self._pending: tuple[str, str] = ("", "")
        self._hwnd = None
        self._hicon = None
        self._added = False
        self._on_event = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        # Ссылка держит callback живым: иначе сборщик мусора освободит его,
        # пока окно ещё получает сообщения.
        self._wndproc = WNDPROC(self._window_proc)
        self._taskbar_created = 0

    # --- вызовы из главного потока ---

    def start(self, on_event) -> None:
        self._on_event = on_event
        self._thread = threading.Thread(target=self._run, name="tenga-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("Tray window did not start")
        if not self._hwnd:
            raise RuntimeError("Tray window could not be created")

    def update(self, icon_path: str, tooltip: str) -> None:
        with self._lock:
            self._pending = (icon_path, tooltip)
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, WM_APP_UPDATE, 0, 0)

    def stop(self) -> None:
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)

    # --- поток окна ---

    def show_menu(self, ops) -> int:
        """Показать меню и вернуть id выбранного пункта (0 — закрыто без выбора)."""
        menu = self._build_menu(ops)
        try:
            point = wintypes.POINT()
            self._user32.GetCursorPos(ctypes.byref(point))
            # Без SetForegroundWindow меню не закрывается щелчком мимо него
            # (известная особенность Shell_NotifyIcon).
            self._user32.SetForegroundWindow(self._hwnd)
            chosen = self._user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                point.x, point.y, 0, self._hwnd, None,
            )
            self._user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            return int(chosen)
        finally:
            self._user32.DestroyMenu(menu)

    def _build_menu(self, ops):
        from src.ui.tray.win32.menu_ops import Entry, Popup, Separator

        menu = self._user32.CreatePopupMenu()
        for op in ops:
            if isinstance(op, Separator):
                self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            elif isinstance(op, Popup):
                sub = self._build_menu(op.children)
                self._user32.AppendMenuW(menu, MF_POPUP, sub, op.label)
            elif isinstance(op, Entry):
                flags = MF_STRING
                if not op.enabled:
                    flags |= MF_GRAYED
                if op.checked:
                    flags |= MF_CHECKED
                self._user32.AppendMenuW(menu, flags, op.id, op.label)
        return menu

    def _run(self) -> None:
        try:
            hinstance = self._kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = self.CLASS_NAME
            self._user32.RegisterClassExW(ctypes.byref(wc))
            self._taskbar_created = self._user32.RegisterWindowMessageW("TaskbarCreated")
            self._hwnd = self._user32.CreateWindowExW(
                0, self.CLASS_NAME, "Tenga Proxy", 0, 0, 0, 0, 0, None, None, hinstance, None
            )
        finally:
            self._ready.set()
        if not self._hwnd:
            logger.error("CreateWindowExW failed: %s", ctypes.get_last_error())
            return

        msg = wintypes.MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _notify_data(self, flags: int) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_APP_TRAY
        return data

    def _apply_pending(self) -> None:
        with self._lock:
            icon_path, tooltip = self._pending
        if icon_path:
            hicon = self._user32.LoadImageW(
                None, icon_path, IMAGE_ICON,
                self._user32.GetSystemMetrics(SM_CXSMICON),
                self._user32.GetSystemMetrics(SM_CYSMICON),
                LR_LOADFROMFILE,
            )
            if hicon:
                if self._hicon:
                    self._user32.DestroyIcon(self._hicon)
                self._hicon = hicon
        data = self._notify_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        data.hIcon = self._hicon
        data.szTip = tooltip
        self._added = bool(
            self._shell32.Shell_NotifyIconW(NIM_MODIFY if self._added else NIM_ADD, ctypes.byref(data))
        ) or self._added

    def _window_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_APP_UPDATE:
                self._apply_pending()
                return 0
            if msg == WM_APP_TRAY:
                if lparam == WM_LBUTTONUP:
                    self._on_event("primary")
                elif lparam == WM_RBUTTONUP:
                    self._on_event("menu")
                return 0
            if msg == self._taskbar_created and self._taskbar_created:
                self._added = False
                self._apply_pending()
                return 0
            if msg == WM_CLOSE:
                self._user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self._added:
                    self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._notify_data(0)))
                    self._added = False
                if self._hicon:
                    self._user32.DestroyIcon(self._hicon)
                    self._hicon = None
                self._hwnd = None
                self._user32.PostQuitMessage(0)
                return 0
        except Exception:
            # Исключение из WNDPROC ctypes проглотит молча; пишем в лог сами.
            logger.exception("Tray window procedure failed")
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)
```

Добавить тест с маркером `windows` (в CI он проверяет хотя бы создание окна и
корректность сигнатур ctypes):

```python
@pytest.mark.windows
def test_real_window_starts_and_stops(tmp_path):
    from src.ui.tray.win32.backend import NotifyIconWindow

    window = NotifyIconWindow()
    window.start(lambda kind: None)
    window.update("", "Tenga Proxy test")
    window.stop()
```

В CI у раннера может не быть Проводника — тогда `Shell_NotifyIconW` вернёт
FALSE, но окно и поток всё равно должны подняться и завершиться без ошибок.

**Step 6: Lint**

Run: `python cli.py lint-all`
Expected: чисто (длинные сигнатуры ctypes разбить по строкам под 100 символов)

**Step 7: Commit**

```bash
git add src/ui/tray/win32/item.py src/ui/tray/win32/backend.py tests/test_ui_tray_win32_item.py
git commit -m "feat(tray): иконка в области уведомлений Windows"
```

---

### Task 2.4: `TrayController` выбирает элемент по ОС

**Files:**
- Modify: `src/ui/tray/controller.py` (`__init__`, ветка `if item is None`)
- Test: `tests/test_ui_tray_controller.py` (если такого файла нет — найти, где тестируется `TrayController`: `grep -rln TrayController tests`)

**Step 1: Write the failing test**

```python
def test_windows_uses_win32_item(monkeypatch):
    from src.core import platform_info
    from src.ui.tray import controller
    from src.ui.tray.win32 import item as win32_item

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    created = []

    class FakeItem:
        def __init__(self, **_kwargs):
            created.append(self)

    monkeypatch.setattr(win32_item, "Win32TrayItem", FakeItem)

    controller.TrayController(object(), object())

    assert len(created) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_controller.py -k windows -v --no-cov`
Expected: FAIL — создаётся `StatusNotifierItem` (или падает импорт Gio)

**Step 3: Write minimal implementation**

```python
        if item is None:
            item = _default_item()
```

```python
def _default_item():
    """Панель Linux говорит по D-Bus (SNI), Windows — через Shell_NotifyIcon."""
    from src.core import platform_info

    if platform_info.IS_WINDOWS:
        from src.ui.tray.win32 import item as win32_item

        return win32_item.Win32TrayItem()
    from src.ui.tray.sni import StatusNotifierItem

    return StatusNotifierItem()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_ui_tray_controller.py -v --no-cov` и `make test-tray`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/ui/tray/controller.py tests/test_ui_tray_controller.py
git commit -m "feat(tray): трей Win32 на Windows, SNI на Linux"
```

---

### Task 2.5: Спецификация PyInstaller

**Files:**
- Create: `packaging/windows/tenga-proxy.spec`
- Create: `packaging/windows/version_info.py` (генератор ресурса версии)
- Modify: `.gitignore` (`build/windows/`, `dist/windows/`)

Проверяется только сборкой на Windows (задача 2.8 и CI). Образец для сверки —
сборка Gaphor (`packaging/` в репозитории gaphor/gaphor): хуки `gi` и набор
`hooksconfig` там проверены на GTK4 + libadwaita.

**Step 1: Спецификация**

`packaging/windows/tenga-proxy.spec`:

```python
# PyInstaller spec для Windows (MSYS2 UCRT64). Запуск: core/scripts/build_windows.sh
# Сборка onedir: onefile распаковывался бы во временный каталог при каждом
# запуске, а GTK-рантайм весит под сотню мегабайт.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821 (SPECPATH задаёт PyInstaller)

datas = [
    (str(ROOT / "assets"), "assets"),
]
binaries = [
    (str(ROOT / "core" / "bin" / "xray.exe"), "core/bin"),
    (str(ROOT / "core" / "bin" / "wintun.dll"), "core/bin"),
    (str(ROOT / "core" / "bin" / "geoip.dat"), "core/bin"),
    (str(ROOT / "core" / "bin" / "geosite.dat"), "core/bin"),
]

hooksconfig = {
    "gi": {
        "icons": ["Adwaita", "hicolor"],
        "themes": ["Adwaita"],
        "languages": ["ru", "en"],
        "module-versions": {"Gtk": "4.0", "Gdk": "4.0"},
    },
}

gui = Analysis(  # noqa: F821
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["gi.repository.Adw", "gi.repository.Gtk", "gi.repository.Gdk"],
    hooksconfig=hooksconfig,
    excludes=["tkinter", "gi.repository.Gtk3"],
)
gui_pyz = PYZ(gui.pure)  # noqa: F821
gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="tenga-proxy",
    icon=str(ROOT / "assets" / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=False,
)

coll = COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    name="tenga-proxy",
)
```

В фазе 3 сюда добавится второй `Analysis`/`EXE` для службы с общим `COLLECT`.

**Step 2: Ресурс версии**

`packaging/windows/version_info.py` — скрипт, который читает `__version__` из
`src/__init__.py` и пишет `build/windows/version_info.txt` в формате
`VSVersionInfo` PyInstaller (FileVersion, ProductVersion, ProductName
«Tenga Proxy», CompanyName «Artem G.»). Шаблон формата — в документации
PyInstaller, раздел «Capturing Windows Version Data»
(`pyi-grab_version` на любом exe выводит образец).

**Step 3: Commit**

```bash
git add packaging/windows .gitignore
git commit -m "build: спецификация PyInstaller для Windows"
```

---

### Task 2.6: Установщик Inno Setup

**Files:**
- Create: `packaging/windows/tenga-proxy.iss`

**Step 1: Сценарий**

```iss
; Установщик Tenga Proxy для Windows. Версию передаёт build_windows.sh:
;   iscc /DAppVersion=0.17.0 packaging\windows\tenga-proxy.iss

#ifndef AppVersion
  #error AppVersion is not defined
#endif

[Setup]
AppId={{6F1D2C3B-5A7E-4E0B-9C1D-2A3B4C5D6E7F}
AppName=Tenga Proxy
AppVersion={#AppVersion}
AppPublisher=Artem G.
AppPublisherURL=https://github.com/vebulogmetra/tenga-proxy
DefaultDirName={autopf}\Tenga Proxy
DefaultGroupName=Tenga Proxy
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\windows
OutputBaseFilename=tenga-proxy-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\assets\tenga-proxy.ico
UninstallDisplayIcon={app}\tenga-proxy.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "autostart"; Description: "Запускать Tenga Proxy при входе в систему"; Flags: unchecked

[Files]
Source: "..\..\dist\windows\tenga-proxy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Tenga Proxy"; Filename: "{app}\tenga-proxy.exe"
Name: "{autodesktop}\Tenga Proxy"; Filename: "{app}\tenga-proxy.exe"; Tasks: desktopicon

[Registry]
; Автозапуск — для того пользователя, который ставит, без прав администратора при входе.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "Tenga Proxy"; ValueData: """{app}\tenga-proxy.exe"""; Tasks: autostart; \
  Flags: uninsdeletevalue
; Ссылки импорта: аналог MimeType в tenga-proxy.desktop.
Root: HKCU; Subkey: "Software\Classes\veblock"; ValueType: string; ValueData: "URL:veblock"; \
  Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\veblock"; ValueType: string; ValueName: "URL Protocol"; \
  ValueData: ""
Root: HKCU; Subkey: "Software\Classes\veblock\shell\open\command"; ValueType: string; \
  ValueData: """{app}\tenga-proxy.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\wingeon"; ValueType: string; ValueData: "URL:wingeon"; \
  Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\wingeon"; ValueType: string; ValueName: "URL Protocol"; \
  ValueData: ""
Root: HKCU; Subkey: "Software\Classes\wingeon\shell\open\command"; ValueType: string; \
  ValueData: """{app}\tenga-proxy.exe"" ""%1"""

[Run]
Filename: "{app}\tenga-proxy.exe"; Description: "{cm:LaunchProgram,Tenga Proxy}"; \
  Flags: nowait postinstall skipifsilent runasoriginaluser
```

`HKCU` при `PrivilegesRequired=admin` — это ветка того администратора, от
имени которого идёт установка. Для обычного сценария (пользователь сам
повышает права через UAC) это он и есть. Отметить ограничение в документации
фазы 4.

`AppId` — сгенерировать свой GUID (`python -c "import uuid; print(uuid.uuid4())"`)
и больше никогда не менять: по нему установщик находит прежнюю версию.

**Step 2: Commit**

```bash
git add packaging/windows/tenga-proxy.iss
git commit -m "build: установщик Inno Setup для Windows"
```

---

### Task 2.7: Сценарий сборки и `cli.py build` на Windows

**Files:**
- Create: `core/scripts/build_windows.sh`
- Modify: `cli.py` (`cmd_build`, `cmd_setup`, `cmd_install`)
- Test: `tests/test_cli_build.py`

**Step 1: Write the failing test**

```python
"""Выбор сценария сборки по ОС."""

from __future__ import annotations

import cli


def test_build_script_on_windows(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert cli.build_script_path().name == "build_windows.sh"


def test_build_script_on_linux(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert cli.build_script_path().name == "build_appimage.sh"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_build.py -v --no-cov`
Expected: FAIL, `AttributeError: build_script_path`

**Step 3: Write minimal implementation**

В `cli.py`:

```python
def build_script_path() -> Path:
    """Сценарий сборки дистрибутива для текущей ОС."""
    from src.core import platform_info

    scripts = Path(__file__).parent / "core" / "scripts"
    return scripts / ("build_windows.sh" if platform_info.IS_WINDOWS else "build_appimage.sh")
```

`cmd_build` использует `build_script_path()`; проверку бинарника делать по
`XRAY_BINARY_NAME` из `src.core.config`; заголовок «AppImage Build» заменить на
нейтральный. `cmd_install` и `cmd_setup` на Windows печатают «Запустите
установщик из dist/windows/» и возвращают 1 — установку в систему на Windows
делает Inno Setup.

`core/scripts/build_windows.sh` (выполняется в MSYS2 UCRT64):

```bash
#!/bin/bash
# Сборка установщика Tenga Proxy для Windows. Выполнять в оболочке MSYS2 UCRT64.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

VERSION="$(python -c 'import re,pathlib; print(re.search(r"__version__ = \"(.+?)\"", pathlib.Path("src/__init__.py").read_text()).group(1))')"

for f in xray.exe wintun.dll geoip.dat geosite.dat; do
    [ -f "core/bin/$f" ] || { echo "[ERROR] core/bin/$f не найден: bash core/scripts/install_dev.sh"; exit 1; }
done
for f in assets/tenga-proxy.ico assets/icons/win/tenga-proxy-connected.ico; do
    [ -f "$f" ] || { echo "[ERROR] $f не найден: uv run python tools/make_ico.py"; exit 1; }
done

mkdir -p build/windows
python packaging/windows/version_info.py build/windows/version_info.txt

python -m PyInstaller --noconfirm --clean \
    --workpath build/windows/pyinstaller --distpath dist/windows \
    packaging/windows/tenga-proxy.spec

# Самопроверка: собранное приложение видит GTK и libadwaita.
[ -f dist/windows/tenga-proxy/tenga-proxy.exe ] || { echo "[ERROR] exe не собран"; exit 1; }

ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"
"$ISCC" "/DAppVersion=$VERSION" packaging/windows/tenga-proxy.iss

echo "[OK] dist/windows/tenga-proxy-$VERSION-windows-x64-setup.exe"
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_cli_build.py tests/test_cli_bump_version.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add core/scripts/build_windows.sh cli.py tests/test_cli_build.py
git commit -m "build: python cli.py build собирает установщик на Windows"
```

---

### Task 2.8: CI на `windows-latest`

**Files:**
- Create: `.github/workflows/windows.yml`

**Step 1: Workflow**

```yaml
name: Windows

on:
  push:
    branches: [develop, master]
  pull_request:
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    defaults:
      run:
        shell: msys2 {0}
    steps:
      - uses: actions/checkout@v4

      - uses: msys2/setup-msys2@v2
        with:
          msystem: UCRT64
          update: true
          install: >-
            git unzip
            mingw-w64-ucrt-x86_64-python
            mingw-w64-ucrt-x86_64-python-pip
            mingw-w64-ucrt-x86_64-python-gobject
            mingw-w64-ucrt-x86_64-gtk4
            mingw-w64-ucrt-x86_64-libadwaita
            mingw-w64-ucrt-x86_64-python-requests
            mingw-w64-ucrt-x86_64-python-pytest
            mingw-w64-ucrt-x86_64-python-pytest-cov
            mingw-w64-ucrt-x86_64-python-pywin32

      - name: Python tools
        run: |
          python -m venv --system-site-packages .venv-win
          . .venv-win/bin/activate
          pip install pyinstaller pyinstaller-hooks-contrib

      - name: xray-core and wintun
        run: bash core/scripts/install_dev.sh

      - name: Tests
        run: |
          . .venv-win/bin/activate
          python -m pytest -q --no-cov

      - name: Build installer
        run: |
          . .venv-win/bin/activate
          bash core/scripts/build_windows.sh

      - uses: actions/upload-artifact@v4
        with:
          name: tenga-proxy-windows-setup
          path: dist/windows/*.exe
          if-no-files-found: error
```

`install_dev.sh` в CI не должен ничего спрашивать интерактивно; если он
задаёт вопросы (`read -p`), добавить в задаче 1.12 режим без вопросов
(`CI=true` → ответ по умолчанию) и проверить здесь.

**Step 2: Проверить на GitHub**

Run: `git push` в ветку, затем `gh run watch` (или `gh run list --workflow windows.yml`)
Expected: job зелёный, артефакт `tenga-proxy-windows-setup` на месте.
Если сборка падает на хуках `gi`, сверить `hooksconfig` со сборкой Gaphor и
записать найденное в «Статус».

**Step 3: Commit**

```bash
git add .github/workflows/windows.yml
git commit -m "ci: тесты и сборка установщика на windows-latest"
```

---

### Task 2.9: Ручная приёмка фазы 2 на VM (владелец проекта)

1. Скачать артефакт из CI, запустить установщик: UAC, мастер на русском,
   задачи «ярлык на рабочем столе» и «автозапуск».
2. Запуск из меню «Пуск»: окно открывается, иконка приложения в панели задач
   и в заголовке.
3. Иконка в трее: подсказка «Tenga Proxy: отключено». Левый щелчок открывает
   окно, правый — меню; «Профили» раскрываются, галочка у активного.
4. Подключиться из меню трея: иконка меняется на «подключено», системный
   прокси включён, сайты открываются. Отключиться: прокси выключен.
5. Перезапустить `explorer.exe` (Диспетчер задач): иконка в трее вернулась.
6. Ссылка `veblock://…` из браузера открывает приложение с диалогом импорта.
7. Выйти из системы и войти: при включённом автозапуске приложение стартует.
8. Удалить через «Приложения»: каталог в Program Files удалён, `%APPDATA%\tenga-proxy`
   остался (настройки пользователя не удаляются).
9. Тёмная тема Windows: окно в тёмной теме (если нет — записать; исправление
   в фазе 4).

Результаты — в «Статус».

---

## Статус

Код фазы выполнен (2026-10-23), задачи 2.1–2.8. На `windows-latest` зелёные
тесты Windows-кода (включая настоящее окно трея `Shell_NotifyIcon`) и сборка
установщика `tenga-proxy-<версия>-windows-x64-setup.exe` (артефакт CI
`tenga-proxy-windows-setup`). Ручная приёмка 2.9 ждёт VM владельца.

Отклонения от плана и найденное в CI:

- **Трей.** Сигнатуры функций ctypes задаются списком пар, а не словарём:
  указатели на функции ctypes не хешируются (`TypeError` на первом прогоне).
- **Кодировка.** Python 3.14 из MSYS2 по умолчанию читает файлы в cp1252, и
  сборка падала на `UnicodeDecodeError`. В exe включён режим UTF-8
  (`PYTHON_OPTIONS` в spec, `X utf8_mode=1`), в CI — `PYTHONUTF8=1`. Версию
  `build_windows.sh` берёт через `packaging/windows/version_info.py`.
- **Полный прогон тестов на Windows** — информационный шаг CI:
  `--continue-on-collection-errors`, тесты модулей с `fcntl` пропускаются,
  фикстура `Gio.TestDBus` трея на Windows пропускается (она роняет процесс
  `abort()`). Прогон нашёл одну ошибку продукта — `os.O_NOFOLLOW` в экспорте
  диагностики (исправлено); остальные падения были в самих тестах.
