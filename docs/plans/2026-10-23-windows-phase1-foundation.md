# Фаза 1. Фундамент Windows-порта — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Контекст: `docs/plans/2026-10-23-windows-port-design.md`, дорожная карта
> `docs/plans/2026-10-23-windows-port-plan.md` (там общие правила и окружение MSYS2).

**Goal:** Приложение из исходников запускается в MSYS2 на Windows и подключается в режиме системного прокси; Linux-поведение не меняется.

**Architecture:** Модули `src/sys/` переезжают в `src/sys/linux/`, на их месте остаются фасады, которые выбирают реализацию по `src.core.platform_info.IS_WINDOWS`. Windows-реализации лежат в `src/sys/windows/` и импортируются на Linux: всё системное (реестр, kernel32, PowerShell) вызывается лениво или через внедряемый объект, поэтому логика тестируется обычным pytest. TUN и VPN-подключения на Windows в этой фазе честно отвечают «пока не поддерживается»: их реализуют фазы 3 и 4.

**Tech Stack:** Python 3.11, stdlib (`winreg`, `ctypes`, `multiprocessing.connection`), PowerShell 5.1 с `ConvertTo-Json`, pytest, ruff, uv.

---

## Принятые решения

- **Имя модуля платформы — `platform_info`, а не `platform`**, чтобы не путать
  со stdlib `platform`, который уже импортирует `src/core/app_update.py`.
- **Сведения о сети — PowerShell + JSON**, а не `route print`/`netsh show`:
  вывод последних переведён на язык системы. Вызов PowerShell стоит ~0,5 с,
  поэтому снимок сети кэшируется на 2 секунды: при подключении сборщик конфига
  спрашивает интерфейс, DNS и VPN подряд.
- **WinINet: одна строка `127.0.0.1:<port>` для всех протоколов.** Вход ядра
  смешанный (HTTP и SOCKS на одном порту), а `socks=` в WinINet означает
  SOCKS4. Так же делает v2rayN.
- **Единственный экземпляр на Windows** — именованный mutex, имя зависит от
  каталога конфигурации (как файл блокировки на Linux). Активация окна первого
  экземпляра — через `multiprocessing.connection` на named pipe.
- Тексты ошибок импорта GTK в `gui.py` (`sudo apt install …`) в этой фазе не
  трогаются: на Windows GTK входит в установщик, текст правится в фазе 4.

---

### Task 1.0: Разведка на Windows VM (вручную, владелец проекта)

Исполнитель на Linux эту задачу не выполняет. Остальные задачи фазы от неё не
блокируются: у каждого риска есть запасной вариант (дорожная карта, «Риски»).
Результаты записываются в раздел «Статус» в конце этого файла.

**Шаги (PowerShell от администратора, Windows 10/11 x64):**

1. Установить MSYS2 и пакеты из дорожной карты. Записать, какие пакеты не
   нашлись (особенно `python-pywin32`).
2. Скачать `Xray-windows-64.zip` версии 26.9.9 и `wintun-0.14.1.zip` с
   https://www.wintun.net/ (взять `wintun/bin/amd64/wintun.dll`, положить рядом
   с `xray.exe`). Записать sha256 обоих архивов — они закрепляются в задаче 1.12.
3. **Статистика по unix-сокету:**
   ```powershell
   # config-stats.json: socks-inbound на 127.0.0.1:10808, outbound freedom,
   # "stats":{}, "api":{"tag":"api","services":["StatsService"]},
   # inbound "api": {"listen":"C:\\Users\\<user>\\AppData\\Local\\Temp\\tenga-test\\stats.sock",
   #                 "protocol":"dokodemo-door","settings":{"address":"127.0.0.1"}}
   .\xray.exe -config config-stats.json
   .\xray.exe api statsquery --server=unix://C:\Users\<user>\AppData\Local\Temp\tenga-test\stats.sock
   ```
   Записать: работает ли, и в каком виде нужен путь после `unix://`.
4. **TUN:** inbound `{"protocol":"tun","settings":{"name":"xray0","MTU":1500,"gateway":["198.18.0.1/30"]}}`,
   запуск от администратора. `Get-NetAdapter xray0` — адаптер появился?
   Какое у него `InterfaceAlias` и `InterfaceDescription`?
5. **Привязка к интерфейсу:** outbound freedom с
   `"streamSettings":{"sockopt":{"interface":"Ethernet"}}` (имя из
   `Get-NetAdapter`). Запросы через него проходят? Ошибки в логе xray?
6. **GTK:** склонировать репозиторий, `python gui.py`. Окно открывается?
   Тёмная тема Windows подхватывается libadwaita?

**Итог:** заполненный раздел «Статус». Если пункт 3 или 5 не работает,
задачи 1.4 и фаза 3 используют запасные варианты из дорожной карты.

---

### Task 1.1: Модуль платформы и маркер `windows`

**Files:**
- Create: `src/core/platform_info.py`
- Modify: `pyproject.toml` (секция `[tool.pytest.ini_options]`, список `markers`)
- Modify: `tests/conftest.py`
- Test: `tests/test_core_platform_info.py`

**Step 1: Write the failing test**

```python
"""Признак платформы и флаги запуска дочерних процессов."""

from __future__ import annotations

from src.core import platform_info


def test_no_window_is_empty_outside_windows(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert platform_info.no_window() == {}


def test_no_window_hides_console_on_windows(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert platform_info.no_window() == {"creationflags": 0x08000000}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_platform_info.py -v --no-cov`
Expected: FAIL, `ImportError: cannot import name 'platform_info'`

**Step 3: Write minimal implementation**

`src/core/platform_info.py`:

```python
"""Какая ОС под приложением и как на ней запускать дочерние процессы.

Признак читается в момент вызова, а не при импорте модулей-потребителей:
тесты подменяют `IS_WINDOWS` и проверяют Windows-ветки на Linux.
"""

from __future__ import annotations

import sys

IS_WINDOWS: bool = sys.platform == "win32"

# Без этого флага каждый вызов консольной программы (xray, PowerShell) из
# оконного приложения на мгновение открывает окно консоли.
CREATE_NO_WINDOW = 0x08000000


def no_window() -> dict:
    """Аргументы subprocess, скрывающие окно консоли; вне Windows — пусто.

    На POSIX subprocess отвергает ненулевой `creationflags`, поэтому ключ
    добавляется только на Windows.
    """
    if IS_WINDOWS:
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
```

В `pyproject.toml` дополнить `markers`:

```toml
markers = [
    "gtk: requires a display, run through make test-gtk",
    "windows: requires real Windows, skipped elsewhere",
]
```

В `tests/conftest.py` добавить после импортов:

```python
import sys


def pytest_collection_modifyitems(config, items):
    """Тесты с маркером `windows` идут только на Windows (в CI — job windows)."""
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="requires Windows")
    for item in items:
        if "windows" in item.keywords:
            item.add_marker(skip)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core_platform_info.py -v --no-cov`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/core/platform_info.py pyproject.toml tests/conftest.py tests/test_core_platform_info.py
git commit -m "feat(core): признак платформы и запуск процессов без окна консоли"
```

---

### Task 1.2: Дочерние процессы без окна консоли

**Files:**
- Modify: `src/core/xray_manager.py` (`start`: `subprocess.Popen`; `_fetch_version`, `_query_stats`: `subprocess.run`)
- Modify: `src/core/batch_probe.py` (оба вызова subprocess, ~строки 130 и 213)
- Modify: `src/core/config.py` (`find_xray_binary`: оба `subprocess.run`)
- Test: `tests/test_core_xray_manager.py`, `tests/test_core_batch_probe.py`

**Step 1: Write the failing test**

В `tests/test_core_xray_manager.py` (посмотреть, как там создаётся
`XrayManager` с фиктивным бинарником, и использовать тот же приём):

```python
def test_core_is_started_without_console_window(monkeypatch, tmp_path):
    from src.core import platform_info, xray_manager

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)
            self.stdout = None
            self.pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(xray_manager.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(xray_manager.XrayManager, "_fetch_version", lambda self: None)
    monkeypatch.setattr(
        xray_manager.XrayManager, "_wait_for_process_ready", lambda self, timeout=2.0: True
    )
    manager = xray_manager.XrayManager(binary_path=str(tmp_path / "xray"))

    ok, _error = manager.start({"inbounds": [], "outbounds": []})

    assert ok
    assert seen["creationflags"] == platform_info.CREATE_NO_WINDOW
```

Аналогичный тест для `batch_probe`: подменить `subprocess.Popen`/`run` в
модуле, включить `IS_WINDOWS`, проверить `creationflags` в kwargs.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_xray_manager.py -k console -v --no-cov`
Expected: FAIL, `KeyError: 'creationflags'`

**Step 3: Write minimal implementation**

В каждый вызов `subprocess.run(...)`/`subprocess.Popen(...)` перечисленных
функций добавить `**no_window()`; импорт:

```python
from src.core.platform_info import no_window
```

Пример для `XrayManager.start`:

```python
            self._process = subprocess.Popen(
                [self._binary_path, "-config", str(self._config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._core_env(),
                **no_window(),
            )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_xray_manager.py tests/test_core_batch_probe.py tests/test_core_config.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/core/xray_manager.py src/core/batch_probe.py src/core/config.py tests/test_core_xray_manager.py tests/test_core_batch_probe.py
git commit -m "feat(core): xray и пробы запускаются без окна консоли на Windows"
```

---

### Task 1.3: Пути и имя бинарника на Windows

**Files:**
- Modify: `src/core/config.py`
- Test: `tests/test_core_config.py`

**Step 1: Write the failing tests**

Дописать в `tests/test_core_config.py`, используя его фикстуру `clean_env` и
`_reload_config_module`:

```python
@pytest.fixture
def as_windows(monkeypatch, clean_env, tmp_path):
    """Windows-ветка `config` на Linux: признак платформы и переменные окружения."""
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    yield tmp_path
    # Следующие тесты должны видеть модуль в Linux-состоянии.
    monkeypatch.undo()
    _reload_config_module()


def test_windows_frozen_uses_appdata(as_windows, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(as_windows / "bundle"), raising=False)

    config = _reload_config_module()

    assert config.CORE_DIR == as_windows / "Roaming" / "tenga-proxy"
    assert config.LOG_DIR == as_windows / "Local" / "tenga-proxy" / "logs"


def test_windows_binary_name_has_exe(as_windows):
    config = _reload_config_module()

    assert config.XRAY_BINARY_NAME == "xray.exe"


def test_windows_env_var_still_wins(as_windows, monkeypatch):
    custom = as_windows / "custom"
    monkeypatch.setenv("TENGA_CONFIG_DIR", str(custom))

    config = _reload_config_module()

    assert config.CORE_DIR == custom
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_core_config.py -k windows -v --no-cov`
Expected: FAIL (`CORE_DIR` указывает в `~/.config`, имя бинарника `xray`)

**Step 3: Write minimal implementation**

В `src/core/config.py`:

```python
from src.core import platform_info


def _windows_dir(variable: str, fallback: str) -> Path:
    """Каталог из переменной окружения Windows (`APPDATA`, `LOCALAPPDATA`)."""
    return Path(os.environ.get(variable) or os.path.expanduser(fallback))
```

В `_get_config_dir` перед XDG-веткой:

```python
    if _is_frozen() and platform_info.IS_WINDOWS:
        return _windows_dir("APPDATA", "~/AppData/Roaming") / "tenga-proxy"
```

В `_get_log_dir` первой строкой:

```python
    if _is_frozen() and platform_info.IS_WINDOWS and "TENGA_CONFIG_DIR" not in os.environ:
        # Логи не роуминговые: им место в Local, а не в Roaming.
        return _windows_dir("LOCALAPPDATA", "~/AppData/Local") / "tenga-proxy" / "logs"
```

Имя бинарника:

```python
XRAY_BINARY_NAME: str = "xray.exe" if platform_info.IS_WINDOWS else "xray"
```

Обновить docstring `_get_config_dir`: перечислить Windows-вариант.

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_config.py -v --no-cov`
Expected: всё зелёное, включая прежние тесты

**Step 5: Commit**

```bash
git add src/core/config.py tests/test_core_config.py
git commit -m "feat(core): каталоги конфигурации и логов Windows, xray.exe"
```

---

### Task 1.4: Каталог сокета статистики на Windows

**Files:**
- Modify: `src/core/stats_endpoint.py`
- Test: `tests/test_core_stats_endpoint.py`

Если разведка (1.0, пункт 3) показала, что unix-сокет на Windows не работает,
вместо этой задачи выполнить запасной вариант из дорожной карты и описать его
в «Статусе».

**Step 1: Write the failing test**

```python
def test_windows_socket_lives_in_default_temp(monkeypatch, tmp_path):
    from src.core import platform_info, stats_endpoint

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(stats_endpoint.tempfile, "tempdir", str(tmp_path))
    endpoint = stats_endpoint.StatsEndpoint()
    try:
        assert endpoint.path.startswith(str(tmp_path))
    finally:
        endpoint.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_stats_endpoint.py -k windows -v --no-cov`
Expected: FAIL — путь начинается с `/tmp`

**Step 3: Write minimal implementation**

```python
from src.core import platform_info

...
            # /tmp — ради лимита длины AF_UNIX на Linux. На Windows /tmp нет,
            # а %TEMP% короткий и принадлежит пользователю.
            directory = None if platform_info.IS_WINDOWS else "/tmp"
            self._directory = tempfile.TemporaryDirectory(prefix="tenga-api-", dir=directory)
```

Обновить docstring модуля: права на Windows задаёт ACL профиля пользователя,
а не режим 0700.

**Step 4: Run tests**

Run: `uv run pytest tests/test_core_stats_endpoint.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/core/stats_endpoint.py tests/test_core_stats_endpoint.py
git commit -m "feat(core): сокет статистики в %TEMP% на Windows"
```

---

### Task 1.5: Перенос `src/sys/*` в `src/sys/linux/` и фасады (рефакторинг)

Чистый рефакторинг: поведение не меняется, ни один тест не меняет утверждений,
только импорты.

**Files:**
- Move: `src/sys/{proxy,vpn,resolver,tun_route,tun_dns,single_instance}.py` → `src/sys/linux/`
- Create: `src/sys/linux/__init__.py`, `src/sys/windows/__init__.py` (пустые, с однострочным docstring)
- Create: фасады `src/sys/{proxy,vpn,resolver,tun_route,tun_dns,single_instance}.py`
- Modify: `src/sys/linux/tun_dns.py` (импорт из `src.sys.linux.tun_route`)
- Modify: тесты `tests/test_sys_*.py` (импорт реализации)
- Create: `tests/test_sys_facades.py`

**Step 1: Переместить модули**

```bash
mkdir -p src/sys/linux src/sys/windows
for m in proxy vpn resolver tun_route tun_dns single_instance; do git mv src/sys/$m.py src/sys/linux/$m.py; done
printf '"""Linux implementations behind the src.sys facades."""\n' > src/sys/linux/__init__.py
printf '"""Windows implementations behind the src.sys facades."""\n' > src/sys/windows/__init__.py
sed -i 's/from src.sys.tun_route import/from src.sys.linux.tun_route import/' src/sys/linux/tun_dns.py
```

**Step 2: Написать фасады**

Каждый фасад — тонкий модуль, Windows-ветка добавляется задачей, которая
пишет Windows-реализацию. Пока ветки нет, фасад импортирует Linux-модуль на
любой ОС.

`src/sys/proxy.py`:

```python
"""Системный прокси. Реализация выбирается по ОС, имена одни и те же."""

from src.sys.linux.proxy import clear_system_proxy, set_system_proxy

__all__ = ["clear_system_proxy", "set_system_proxy"]
```

`src/sys/vpn.py`:

```python
"""VPN-подключения и сетевые интерфейсы. Реализация выбирается по ОС."""

from src.sys.linux.vpn import (
    connect_vpn,
    disconnect_vpn,
    get_default_interface,
    get_vpn_dns_servers,
    get_vpn_interface,
    get_vpn_interface_ip,
    is_vpn_active,
    list_network_interfaces,
    list_vpn_connections,
)

__all__ = [
    "connect_vpn",
    "disconnect_vpn",
    "get_default_interface",
    "get_vpn_dns_servers",
    "get_vpn_interface",
    "get_vpn_interface_ip",
    "is_vpn_active",
    "list_network_interfaces",
    "list_vpn_connections",
]
```

`src/sys/resolver.py` — `system_dns_servers`; `src/sys/tun_route.py` —
`TunRouteState`, `apply_tun_routes`, `restore_tun_routes`;
`src/sys/tun_dns.py` — `TUN_DNS_ADDRESS`, `route_system_dns_to_tun`;
`src/sys/single_instance.py` — `SingleInstance`. Docstring у каждого по
образцу выше.

**Step 3: Поправить тесты**

В `tests/test_sys_*.py` заменить `from src.sys import X` на
`from src.sys.linux import X`, а `from src.sys.X import …` — на
`from src.sys.linux.X import …`. Строковые пути в monkeypatch
(`"src.sys.single_instance.Path.read_text"` и подобные) — на
`"src.sys.linux.single_instance…"`. `tests/test_core_monitor.py` патчит
`"src.sys.vpn.is_vpn_active"`: монитор импортирует функцию из фасада в момент
вызова, поэтому этот путь оставить как есть.

Проверка, что ничего не забыто:

```bash
grep -rnE "src\.sys\.(proxy|vpn|resolver|tun_route|tun_dns|single_instance)\b" tests | grep -v test_core_monitor
```
Expected: пусто, кроме фасадного теста ниже.

**Step 4: Тест паритета фасадов**

`tests/test_sys_facades.py`:

```python
"""Фасады src.sys отдают одинаковый набор имён на любой ОС."""

from __future__ import annotations

import importlib

import pytest

FACADES = ["proxy", "vpn", "resolver", "tun_route", "tun_dns", "single_instance"]


@pytest.mark.parametrize("name", FACADES)
def test_linux_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    linux = importlib.import_module(f"src.sys.linux.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(linux, attr)]

    assert missing == []
```

Тест Windows-модулей добавляется в задачах 1.6–1.11 по мере их появления.

**Step 5: Полный прогон**

Run: `uv run pytest -q` и `python cli.py lint-all`
Expected: всё зелёное, число тестов = прежнее + 6

**Step 6: Commit**

```bash
git add -A src/sys tests
git commit -m "refactor(sys): реализации Linux в src/sys/linux, на месте модулей фасады"
```

---

### Task 1.6: Единственный экземпляр на Windows — mutex

**Files:**
- Create: `src/sys/windows/single_instance.py`
- Modify: `src/sys/single_instance.py` (Windows-ветка)
- Modify: `tests/test_sys_facades.py`
- Test: `tests/test_sys_windows_single_instance.py`

**Step 1: Write the failing tests**

```python
"""Mutex единственного экземпляра: логика без настоящего kernel32."""

from __future__ import annotations

from pathlib import Path

from src.sys.windows.single_instance import SingleInstance, mutex_name


class FakeKernel:
    def __init__(self, existing: set[str] | None = None):
        self.existing = existing or set()
        self.closed: list[int] = []

    def create_mutex(self, name: str) -> tuple[int, bool]:
        already = name in self.existing
        self.existing.add(name)
        return 7, already

    def close(self, handle: int) -> None:
        self.closed.append(handle)


def test_name_depends_on_config_dir():
    first = mutex_name(Path("C:/a/tenga-proxy.lock"))
    second = mutex_name(Path("C:/b/tenga-proxy.lock"))

    assert first.startswith("Local\\ru.tenga.Proxy-")
    assert first != second


def test_name_ignores_case():
    assert mutex_name(Path("C:/A/x.lock")) == mutex_name(Path("c:/a/X.lock"))


def test_first_instance_acquires():
    kernel = FakeKernel()
    instance = SingleInstance(Path("C:/a/x.lock"), kernel=kernel)

    assert instance.acquire() is True


def test_second_instance_is_refused_and_closes_handle():
    lock = Path("C:/a/x.lock")
    kernel = FakeKernel(existing={mutex_name(lock)})
    instance = SingleInstance(lock, kernel=kernel)

    assert instance.acquire() is False
    assert kernel.closed == [7]


def test_release_closes_handle_once():
    kernel = FakeKernel()
    instance = SingleInstance(Path("C:/a/x.lock"), kernel=kernel)
    instance.acquire()

    instance.release()
    instance.release()

    assert kernel.closed == [7]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_single_instance.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/sys/windows/single_instance.py`:

```python
"""Единственный экземпляр на Windows: именованный mutex.

Mutex принадлежит процессу и исчезает вместе с ним, поэтому «устаревших»
блокировок, как с файлом на Linux, не бывает. Имя зависит от каталога
конфигурации: два экземпляра с разными каталогами живут рядом, как на Linux.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger("tenga.sys.single_instance")

ERROR_ALREADY_EXISTS = 183


def mutex_name(lock_file: Path) -> str:
    digest = hashlib.sha1(str(lock_file).lower().encode("utf-8")).hexdigest()[:12]
    return f"Local\\ru.tenga.Proxy-{digest}"


class _Kernel32:
    """Тонкая обёртка над kernel32; импорт ctypes.windll — только на Windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self._dll.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self._dll.CreateMutexW.restype = wintypes.HANDLE
        self._dll.CloseHandle.argtypes = [wintypes.HANDLE]

    def create_mutex(self, name: str) -> tuple[int, bool]:
        handle = self._dll.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(self._ctypes.get_last_error(), "CreateMutexW failed")
        return handle, self._ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close(self, handle: int) -> None:
        self._dll.CloseHandle(handle)


class SingleInstance:
    """Same interface as the Linux file lock."""

    def __init__(self, lock_file: Path, *, kernel=None):
        self._name = mutex_name(lock_file)
        self._kernel = kernel
        self._handle: int | None = None

    def _api(self):
        if self._kernel is None:
            self._kernel = _Kernel32()
        return self._kernel

    def is_running(self) -> bool:
        """Держит ли mutex другой процесс: открыть и сразу закрыть."""
        if self._handle is not None:
            return False
        handle, already = self._api().create_mutex(self._name)
        self._api().close(handle)
        return already

    def acquire(self) -> bool:
        try:
            handle, already = self._api().create_mutex(self._name)
        except OSError as e:
            logger.error("Error acquiring mutex: %s", e)
            return False
        if already:
            self._api().close(handle)
            return False
        self._handle = handle
        logger.info("Mutex acquired: %s", self._name)
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        self._api().close(self._handle)
        self._handle = None
        logger.info("Mutex released")

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another instance is already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
```

Фасад `src/sys/single_instance.py`:

```python
"""Защита от второго экземпляра. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.single_instance import SingleInstance
else:
    from src.sys.linux.single_instance import SingleInstance

__all__ = ["SingleInstance"]
```

В `tests/test_sys_facades.py` добавить:

```python
WINDOWS_READY = ["single_instance"]


@pytest.mark.parametrize("name", WINDOWS_READY)
def test_windows_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    windows = importlib.import_module(f"src.sys.windows.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(windows, attr)]

    assert missing == []
```

Каждая следующая задача, добавляющая Windows-модуль, дописывает его имя в
`WINDOWS_READY`. После задачи 1.11 список совпадает с `FACADES`.

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_single_instance.py tests/test_sys_facades.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/single_instance.py src/sys/single_instance.py tests/test_sys_windows_single_instance.py tests/test_sys_facades.py
git commit -m "feat(sys): единственный экземпляр на Windows через именованный mutex"
```

---

### Task 1.7: Активация окна первого экземпляра на Windows

На Linux второй запуск передаёт `activate`/`open` первому через D-Bus (это
делает `Gio.Application`). На Windows сессионной шины нет: приложение
запускается с `NON_UNIQUE`, а второй экземпляр отправляет ссылки по pipe.

**Files:**
- Create: `src/sys/windows/activation.py`
- Modify: `gui.py` (`main`)
- Modify: `src/ui/application.py` (`__init__` — флаги, `do_startup`/`do_shutdown` — сервер активации)
- Test: `tests/test_sys_windows_activation.py`

**Step 1: Write the failing tests**

Проверка на Linux идёт через тот же `multiprocessing.connection`, только с
`AF_UNIX`: протокол один, меняется лишь семейство адреса.

```python
"""Передача активации от второго экземпляра первому."""

from __future__ import annotations

import threading
import time

from src.sys.windows.activation import ActivationServer, pipe_address, send_activation


def test_address_is_a_named_pipe_per_user_and_config():
    first = pipe_address("C:/a/x.lock", user="alice")
    second = pipe_address("C:/b/x.lock", user="alice")

    assert first.startswith("\\\\.\\pipe\\ru.tenga.Proxy-")
    assert first != second


def test_second_instance_delivers_uris(tmp_path):
    address = str(tmp_path / "activate.sock")
    got = []
    done = threading.Event()

    def on_request(uris):
        got.append(uris)
        done.set()

    server = ActivationServer(address, on_request, family="AF_UNIX")
    server.start()
    try:
        assert send_activation(address, ["veblock://add/x"], family="AF_UNIX") is True
        assert done.wait(5)
    finally:
        server.stop()

    assert got == [["veblock://add/x"]]


def test_send_without_server_reports_failure(tmp_path):
    assert send_activation(str(tmp_path / "none.sock"), [], family="AF_UNIX") is False


def test_garbage_request_is_ignored(tmp_path):
    from multiprocessing.connection import Client

    address = str(tmp_path / "activate.sock")
    got = []
    server = ActivationServer(address, got.append, family="AF_UNIX")
    server.start()
    try:
        with Client(address, family="AF_UNIX", authkey=b"tenga-activate") as conn:
            conn.send({"uris": "not-a-list"})
        # Второй, нормальный запрос доказывает, что поток сервера жив.
        assert send_activation(address, [], family="AF_UNIX") is True
        time.sleep(0.2)
    finally:
        server.stop()

    # Мусор превращается в пустой список, а не доходит до обработчика как есть.
    assert got == [[], []]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_activation.py -v --no-cov`
Expected: FAIL, `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`src/sys/windows/activation.py`:

```python
"""Второй запуск просит первый показать окно и открыть ссылки.

`multiprocessing.connection` даёт на Windows named pipe (`AF_PIPE`), а
`authkey` отсекает случайных собеседников: подключиться может кто угодно из
сессии, но запрос без ключа сервер отбрасывает. Сообщение — словарь
`{"uris": [str, ...]}`, всё прочее игнорируется.
"""

from __future__ import annotations

import getpass
import hashlib
import logging
import threading
from collections.abc import Callable
from multiprocessing.connection import Client, Listener

logger = logging.getLogger("tenga.sys.activation")

AUTHKEY = b"tenga-activate"


def pipe_address(lock_file: str, user: str | None = None) -> str:
    user = user or getpass.getuser()
    digest = hashlib.sha1(f"{user}|{str(lock_file).lower()}".encode()).hexdigest()[:12]
    return f"\\\\.\\pipe\\ru.tenga.Proxy-{digest}"


def send_activation(address: str, uris: list[str], *, family: str = "AF_PIPE") -> bool:
    try:
        with Client(address, family=family, authkey=AUTHKEY) as conn:
            conn.send({"uris": list(uris)})
        return True
    except (OSError, EOFError) as e:
        logger.warning("Activation request failed: %s", e)
        return False


class ActivationServer:
    """Принимает запросы в фоновом потоке и отдаёт их обработчику."""

    def __init__(
        self,
        address: str,
        on_request: Callable[[list[str]], None],
        *,
        family: str = "AF_PIPE",
    ) -> None:
        self._address = address
        self._family = family
        self._on_request = on_request
        self._listener: Listener | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        self._listener = Listener(self._address, family=self._family, authkey=AUTHKEY)
        self._thread = threading.Thread(target=self._serve, name="tenga-activation", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                with self._listener.accept() as conn:
                    message = conn.recv()
            except Exception as e:
                if not self._stopping.is_set():
                    logger.debug("Activation connection dropped: %s", e)
                continue
            if self._stopping.is_set():
                return
            uris = message.get("uris") if isinstance(message, dict) else None
            if not isinstance(uris, list) or not all(isinstance(u, str) for u in uris):
                uris = []
            self._on_request(uris)

    def stop(self) -> None:
        self._stopping.set()
        # accept() блокирует поток: будим его пустым подключением.
        send_activation(self._address, [], family=self._family)
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
```

`gui.py`, в `main()` вместо ветки `if not holds_lock:`:

```python
    if not holds_lock:
        from src.core.platform_info import IS_WINDOWS

        if IS_WINDOWS:
            # Без D-Bus Gio.Application не найдёт первый экземпляр сам.
            from src.sys.windows.activation import pipe_address, send_activation

            delivered = send_activation(pipe_address(str(lock_file)), args.uris)
            return 0 if delivered else 1
        # Приложение всё равно запускается: …  (прежний комментарий и logger.info)
```

`src/ui/application.py`:

- в `__init__` флаги:
  ```python
  flags = Gio.ApplicationFlags.HANDLES_OPEN
  if IS_WINDOWS:
      # Уникальность GApplication держится на D-Bus, которой на Windows нет;
      # её обеспечивают mutex и pipe активации (src/sys/windows).
      flags |= Gio.ApplicationFlags.NON_UNIQUE
  super().__init__(application_id=APP_ID, flags=flags)
  ```
- в `do_startup` после `_setup_signal_handlers()` — `self._start_activation_server()`;
- в `do_shutdown` — `self._stop_activation_server()`;
- методы:
  ```python
  def _start_activation_server(self) -> None:
      if not IS_WINDOWS or self._lock is None:
          return
      from src.sys.windows.activation import ActivationServer, pipe_address

      def deliver(uris: list[str]) -> None:
          def _apply() -> bool:
              self.activate()
              for uri in uris:
                  self.import_app_link(uri)
              return GLib.SOURCE_REMOVE

          GLib.idle_add(_apply)

      self._activation = ActivationServer(pipe_address(str(self._lock_path())), deliver)
      self._activation.start()
  ```
  Проверить, как `TengaApplication` хранит `lock` (параметр `lock=` в
  `__init__`), и взять путь файла блокировки оттуда же, откуда его берёт
  `gui.py` (`get_lock_file(config_dir)`). Если путь не сохраняется, передать
  его в `run_app` отдельным параметром `lock_path`.

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_activation.py tests/test_gui_entrypoint.py -v --no-cov`
Expected: всё зелёное

**Step 5: Commit**

```bash
git add src/sys/windows/activation.py gui.py src/ui/application.py tests/test_sys_windows_activation.py
git commit -m "feat(ui): второй запуск на Windows активирует окно первого через pipe"
```

---

### Task 1.8: Сигналы только на POSIX

**Files:**
- Modify: `src/ui/application.py` (`_setup_signal_handlers`)
- Test: `tests/test_ui_application.py` (тест без GTK-дисплея, если в файле есть такие; иначе новый `tests/test_ui_application_signals.py`)

**Step 1: Write the failing test**

```python
def test_signal_handlers_are_skipped_on_windows(monkeypatch):
    pytest.importorskip("gi")
    from src.core import platform_info
    from src.ui import application

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    calls = []
    monkeypatch.setattr(application.GLib, "unix_signal_add", lambda *a: calls.append(a) or 1)
    app = application.TengaApplication.__new__(application.TengaApplication)

    application.TengaApplication._setup_signal_handlers(app)

    assert calls == []
    assert app._signal_source_ids == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_application_signals.py -v --no-cov`
Expected: FAIL, вызовы `unix_signal_add` есть

**Step 3: Write minimal implementation**

```python
    def _setup_signal_handlers(self) -> None:
        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK).

        На Windows `GLib.unix_signal_add` нет, а закрытие приходит оконными
        сообщениями, которые GTK обрабатывает сам.
        """
        if platform_info.IS_WINDOWS:
            self._signal_source_ids = []
            return
        ...прежний код...
```

Импорт: `from src.core import platform_info` (модуль, а не имя — чтобы
подмена в тесте работала).

**Step 4: Run tests**

Run: `uv run pytest tests/test_ui_application_signals.py -v --no-cov`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ui/application.py tests/test_ui_application_signals.py
git commit -m "fix(ui): не подписываться на POSIX-сигналы на Windows"
```

---

### Task 1.9: Системный прокси Windows (WinINet)

**Files:**
- Create: `src/sys/windows/proxy.py`
- Modify: `src/sys/proxy.py` (Windows-ветка), `tests/test_sys_facades.py` (`WINDOWS_READY`)
- Test: `tests/test_sys_windows_proxy.py`

**Step 1: Write the failing tests**

```python
"""Системный прокси Windows: значения реестра и уведомление WinINet."""

from __future__ import annotations

from src.sys.windows import proxy


class FakeRegistry:
    def __init__(self):
        self.values: dict[str, object] = {}

    def write(self, values: dict[str, object]) -> None:
        self.values.update(values)


def test_values_for_mixed_port():
    values = proxy.proxy_values(http_port=2080, socks_port=2080)

    assert values["ProxyEnable"] == 1
    assert values["ProxyServer"] == "127.0.0.1:2080"
    assert "<local>" in values["ProxyOverride"]
    assert "localhost" in values["ProxyOverride"]


def test_http_port_wins_when_ports_differ():
    assert proxy.proxy_values(http_port=8080, socks_port=1080)["ProxyServer"] == "127.0.0.1:8080"


def test_socks_only_uses_socks_scheme():
    assert proxy.proxy_values(http_port=0, socks_port=1080)["ProxyServer"] == "socks=127.0.0.1:1080"


def test_set_writes_registry_and_notifies(monkeypatch):
    registry = FakeRegistry()
    notified = []

    assert proxy.set_system_proxy(2080, 2080, registry=registry, notify=lambda: notified.append(1))
    assert registry.values["ProxyEnable"] == 1
    assert notified == [1]


def test_nothing_to_set_returns_false():
    assert proxy.set_system_proxy(0, 0, registry=FakeRegistry(), notify=lambda: None) is False


def test_clear_disables_proxy():
    registry = FakeRegistry()

    assert proxy.clear_system_proxy(registry=registry, notify=lambda: None)
    assert registry.values == {"ProxyEnable": 0}


def test_registry_failure_returns_false():
    class Broken:
        def write(self, values):
            raise OSError("access denied")

    assert proxy.set_system_proxy(2080, 2080, registry=Broken(), notify=lambda: None) is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_proxy.py -v --no-cov`
Expected: FAIL, `ImportError`

**Step 3: Write minimal implementation**

`src/sys/windows/proxy.py`:

```python
"""Системный прокси Windows: ключ `Internet Settings` пользователя и WinINet.

Значения читают WinINet (Edge, Chrome, большинство программ) и WinHTTP-клиенты,
импортирующие настройки пользователя. После записи WinINet нужно уведомить, иначе
уже запущенные программы увидят изменение только после перезапуска.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tenga.sys.proxy")

KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

# Адреса, которые не должны идти через прокси: локальные сети и имена без точки.
BYPASS = ";".join(
    [
        "localhost",
        "127.*",
        "10.*",
        "172.16.*",
        "172.17.*",
        "172.18.*",
        "172.19.*",
        "172.2*",
        "172.30.*",
        "172.31.*",
        "192.168.*",
        "<local>",
    ]
)


class _UserRegistry:
    def write(self, values: dict[str, object]) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind, value)


def _notify_wininet() -> None:
    import ctypes

    wininet = ctypes.WinDLL("wininet")
    wininet.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
    wininet.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0)


def proxy_values(http_port: int, socks_port: int, address: str = "127.0.0.1") -> dict[str, object]:
    """Значения реестра. Вход ядра смешанный, поэтому одного HTTP-адреса достаточно."""
    if 0 < http_port < 65536:
        server = f"{address}:{http_port}"
    else:
        # `socks=` WinINet понимает как SOCKS4; ядро его принимает.
        server = f"socks={address}:{socks_port}"
    return {"ProxyEnable": 1, "ProxyServer": server, "ProxyOverride": BYPASS}


def _apply(values: dict[str, object], registry, notify) -> bool:
    try:
        (registry or _UserRegistry()).write(values)
        (notify or _notify_wininet)()
        return True
    except OSError as e:
        logger.error("Cannot change Windows proxy settings: %s", e)
        return False


def set_system_proxy(
    http_port: int = 0,
    socks_port: int = 0,
    address: str = "127.0.0.1",
    *,
    registry=None,
    notify=None,
) -> bool:
    has_http = 0 < http_port < 65536
    has_socks = 0 < socks_port < 65536
    if not has_http and not has_socks:
        return False
    return _apply(proxy_values(http_port, socks_port, address), registry, notify)


def clear_system_proxy(*, registry=None, notify=None) -> bool:
    return _apply({"ProxyEnable": 0}, registry, notify)
```

Фасад `src/sys/proxy.py` — Windows-ветка по образцу задачи 1.6; добавить
`"proxy"` в `WINDOWS_READY`.

Добавить тест с маркером `windows` (идёт только в CI на Windows), который
проверяет запись в настоящий реестр и возвращает прежнее значение:

```python
@pytest.mark.windows
def test_real_registry_roundtrip():
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, proxy.KEY_PATH) as key:
        before = winreg.QueryValueEx(key, "ProxyEnable")[0]
    try:
        assert proxy.set_system_proxy(2080, 2080)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, proxy.KEY_PATH) as key:
            assert winreg.QueryValueEx(key, "ProxyServer")[0] == "127.0.0.1:2080"
    finally:
        proxy._apply({"ProxyEnable": before}, None, None)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_proxy.py tests/test_sys_facades.py -v --no-cov`
Expected: всё зелёное, `test_real_registry_roundtrip` пропущен

**Step 5: Commit**

```bash
git add src/sys/windows/proxy.py src/sys/proxy.py tests/test_sys_windows_proxy.py tests/test_sys_facades.py
git commit -m "feat(sys): системный прокси Windows через реестр и WinINet"
```

---

### Task 1.10: Снимок сети Windows через PowerShell

**Files:**
- Create: `src/sys/windows/powershell.py`
- Create: `src/sys/windows/netinfo.py`
- Test: `tests/test_sys_windows_netinfo.py`

**Step 1: Write the failing tests**

```python
"""Разбор снимка сети Windows: адаптеры, адреса, DNS, маршруты по умолчанию."""

from __future__ import annotations

import json

from src.sys.windows import netinfo

SNAPSHOT = {
    "adapters": [
        {"alias": "Ethernet", "index": 12, "status": "Up", "description": "Intel(R) Ethernet"},
        {"alias": "xray0", "index": 40, "status": "Up", "description": "Wintun Userspace Tunnel"},
        {"alias": "Office", "index": 41, "status": "Up", "description": "WAN Miniport (IKEv2)"},
    ],
    "ips": [
        {"alias": "Ethernet", "ip": "192.168.0.154"},
        {"alias": "xray0", "ip": "198.18.0.1"},
        {"alias": "Office", "ip": "10.8.0.5"},
    ],
    "dns": [
        {"alias": "Ethernet", "servers": ["192.168.0.1", "fe80::1"]},
        {"alias": "Office", "servers": ["10.8.0.1"]},
    ],
    "routes": [
        {"alias": "xray0", "index": 40, "nexthop": "0.0.0.0", "metric": 0, "ifmetric": 5},
        {"alias": "Ethernet", "index": 12, "nexthop": "192.168.0.1", "metric": 0, "ifmetric": 25},
    ],
}


def test_parse_builds_adapters_with_addresses():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    ethernet = snapshot.adapter("Ethernet")
    assert ethernet.ipv4 == ["192.168.0.154"]
    assert ethernet.dns == ["192.168.0.1", "fe80::1"]


def test_single_objects_are_accepted_as_lists():
    """PowerShell сворачивает массив из одного элемента в объект."""
    data = dict(SNAPSHOT, ips={"alias": "Ethernet", "ip": "192.168.0.154"})

    assert netinfo.parse_snapshot(json.dumps(data)).adapter("Ethernet").ipv4 == ["192.168.0.154"]


def test_tunnel_adapters_are_recognised():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    assert netinfo.is_tunnel(snapshot.adapter("xray0"))
    assert netinfo.is_tunnel(snapshot.adapter("Office"))
    assert not netinfo.is_tunnel(snapshot.adapter("Ethernet"))


def test_default_route_skips_tunnels_and_exclusions():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    route = netinfo.default_route(snapshot, exclude=("xray0",))

    assert route.alias == "Ethernet"
    assert route.nexthop == "192.168.0.1"


def test_default_route_none_when_only_tunnels():
    data = dict(SNAPSHOT, routes=[SNAPSHOT["routes"][0]])

    assert netinfo.default_route(netinfo.parse_snapshot(json.dumps(data))) is None


def test_garbage_gives_empty_snapshot():
    assert netinfo.parse_snapshot("not json").adapters == []


def test_snapshot_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(
        netinfo, "run_json", lambda script: calls.append(script) or json.dumps(SNAPSHOT)
    )
    netinfo.invalidate()

    netinfo.snapshot()
    netinfo.snapshot()

    assert len(calls) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_netinfo.py -v --no-cov`
Expected: FAIL, `ImportError`

**Step 3: Write minimal implementation**

`src/sys/windows/powershell.py`:

```python
"""Запуск PowerShell-скрипта с выводом JSON.

Вывод `netsh` и `route print` переведён на язык системы, а объекты PowerShell
сериализуются одинаково на любой локали.
"""

from __future__ import annotations

import logging
import subprocess

from src.core.platform_info import no_window

logger = logging.getLogger("tenga.sys.powershell")


def run_json(script: str, timeout: int = 15) -> str:
    """Stdout скрипта; пустая строка при любой ошибке."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
            **no_window(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("PowerShell failed: %s", e)
        return ""
    if result.returncode != 0:
        logger.warning("PowerShell returned %s: %s", result.returncode, result.stderr.strip())
        return ""
    return result.stdout
```

`src/sys/windows/netinfo.py`:

```python
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

SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$result = @{
  adapters = @(Get-NetAdapter -IncludeHidden | ForEach-Object {
    @{ alias = $_.Name; index = $_.ifIndex; status = [string]$_.Status;
       description = $_.InterfaceDescription } })
  ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
    @{ alias = $_.InterfaceAlias; ip = $_.IPAddress } })
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


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


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
        adapter = adapters.get(str(item.get("alias", "")))
        if adapter and item.get("ip"):
            adapter.ipv4.append(str(item["ip"]))
    for item in _as_list(data.get("dns")):
        adapter = adapters.get(str(item.get("alias", "")))
        if adapter:
            servers = item.get("servers") or []
            adapter.dns.extend(str(s) for s in (servers if isinstance(servers, list) else [servers]))

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
        result = parse_snapshot(run_json(SCRIPT))
        _cached = (now, result)
        return result
```

Добавить тест с маркером `windows`: `netinfo.invalidate(); s = netinfo.snapshot()`,
проверить, что адаптеров больше нуля и у маршрута по умолчанию непустой
`alias`. Этот тест заодно проверяет сам PowerShell-скрипт в CI.

**Step 4: Run tests**

Run: `uv run pytest tests/test_sys_windows_netinfo.py -v --no-cov`
Expected: всё зелёное, Windows-тест пропущен

**Step 5: Commit**

```bash
git add src/sys/windows/powershell.py src/sys/windows/netinfo.py tests/test_sys_windows_netinfo.py
git commit -m "feat(sys): снимок сети Windows через PowerShell"
```

---

### Task 1.11: Windows-модули `vpn`, `resolver`, `tun_route`, `tun_dns`

Интерфейсы и DNS работают по-настоящему. Подключение VPN и TUN в этой фазе
отвечают отказом с понятной причиной: их реализуют фазы 4 и 3.

**Files:**
- Create: `src/sys/addresses.py` (общий `usable_ipv4`)
- Modify: `src/sys/linux/resolver.py` (импорт `usable_ipv4` вместо `_usable_ipv4`)
- Create: `src/sys/windows/vpn.py`, `src/sys/windows/resolver.py`, `src/sys/windows/tun_route.py`, `src/sys/windows/tun_dns.py`
- Modify: фасады `src/sys/{vpn,resolver,tun_route,tun_dns}.py`, `tests/test_sys_facades.py`
- Test: `tests/test_sys_windows_vpn.py`

**Step 1: Вынести `usable_ipv4` (рефакторинг, отдельный коммит)**

`src/sys/addresses.py`:

```python
"""Общие проверки адресов для Linux- и Windows-реализаций."""

from __future__ import annotations

import ipaddress


def usable_ipv4(value: str) -> str | None:
    """IPv4-адрес настоящего сервера; loopback — заглушка локального резолвера."""
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback:
        return None
    return str(address)
```

В `src/sys/linux/resolver.py` удалить `_usable_ipv4`, импортировать
`from src.sys.addresses import usable_ipv4` и заменить вызовы. Если тесты
обращаются к `resolver._usable_ipv4`, оставить в Linux-модуле строку
`_usable_ipv4 = usable_ipv4`.

Run: `uv run pytest tests/test_sys_resolver.py -q --no-cov` → зелёное.

```bash
git add src/sys/addresses.py src/sys/linux/resolver.py
git commit -m "refactor(sys): проверка адреса DNS-сервера в общем модуле"
```

**Step 2: Write the failing tests**

```python
"""Windows-реализация интерфейсов и DNS поверх снимка сети."""

from __future__ import annotations

import json

import pytest

from src.sys.windows import netinfo, resolver, tun_dns, tun_route, vpn
from tests.test_sys_windows_netinfo import SNAPSHOT


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(SNAPSHOT)))


def test_default_interface_is_physical():
    assert vpn.get_default_interface(exclude=("xray0",)) == "Ethernet"


def test_default_interface_respects_vpn_exclusion():
    assert vpn.get_default_interface("Ethernet", exclude=("xray0",)) is None


def test_interfaces_are_listed_by_alias():
    assert vpn.list_network_interfaces() == ["Ethernet", "Office", "xray0"]


def test_interface_ip():
    assert vpn.get_vpn_interface_ip("Office") == "10.8.0.5"


def test_dns_servers_drop_ipv6():
    assert resolver.system_dns_servers("Ethernet") == ["192.168.0.1"]


def test_vpn_connect_is_not_available_yet():
    assert vpn.list_vpn_connections() == []
    assert vpn.connect_vpn("Office") is False


def test_tun_routes_report_why_they_fail():
    ok, state, error = tun_route.apply_tun_routes("xray0", "example.com")

    assert (ok, state) == (False, None)
    assert "служб" in error


def test_restoring_nothing_is_fine():
    assert tun_route.restore_tun_routes(None) == (True, "")


def test_tun_dns_reports_why_it_fails():
    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert ok is False
    assert error
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sys_windows_vpn.py -v --no-cov`
Expected: FAIL, `ImportError`

**Step 4: Write minimal implementation**

`src/sys/windows/vpn.py`:

```python
"""Интерфейсы и VPN на Windows.

Интерфейсы, адреса и DNS берутся из снимка сети. Управление VPN-подключениями
(RAS, WireGuard) появится в фазе 4 порта; до тех пор список пуст, а подключение
отвечает отказом, и профиль работает без VPN — как на Linux без NetworkManager.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.sys.windows import netinfo

logger = logging.getLogger("tenga.sys.vpn")


def list_vpn_connections() -> list[str]:
    return []


def is_vpn_active(connection_name: str) -> bool:
    return False


def get_vpn_interface(connection_name: str) -> str | None:
    return None


def get_vpn_interface_ip(interface_name: str) -> str | None:
    adapter = netinfo.snapshot().adapter(interface_name) if interface_name else None
    return adapter.ipv4[0] if adapter and adapter.ipv4 else None


def connect_vpn(connection_name: str) -> bool:
    logger.warning("VPN connections are not supported on Windows yet: %s", connection_name)
    return False


def disconnect_vpn(connection_name: str) -> bool:
    return False


def get_vpn_dns_servers(connection_name: str) -> list[str]:
    return []


def list_network_interfaces() -> list[str]:
    return sorted(adapter.alias for adapter in netinfo.snapshot().adapters)


def get_default_interface(
    vpn_interface: str | None = None, exclude: Iterable[str] = ()
) -> str | None:
    skipped = set(exclude)
    if vpn_interface:
        skipped.add(vpn_interface)
    route = netinfo.default_route(netinfo.snapshot(), exclude=skipped)
    return route.alias if route else None
```

`src/sys/windows/resolver.py`:

```python
"""DNS-серверы физического интерфейса Windows (для перехвата DNS в TUN)."""

from __future__ import annotations

from src.sys.addresses import usable_ipv4
from src.sys.windows import netinfo


def system_dns_servers(interface: str) -> list[str]:
    adapter = netinfo.snapshot().adapter(interface)
    if adapter is None:
        return []
    servers = [usable_ipv4(server) for server in adapter.dns]
    return [server for server in servers if server]
```

`src/sys/windows/tun_route.py` (заглушка до фазы 3):

```python
"""Маршруты TUN на Windows. Их ставит служба Tenga Proxy (фаза 3 порта)."""

from __future__ import annotations

from dataclasses import dataclass

NO_SERVICE = "TUN-режим на Windows требует службу Tenga Proxy; она ещё не установлена"


@dataclass
class TunRouteState:
    tun_name: str
    proxy_ip: str


def apply_tun_routes(tun_name: str, proxy_host: str) -> tuple[bool, TunRouteState | None, str]:
    return False, None, NO_SERVICE


def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    if state is None:
        return True, ""
    return False, NO_SERVICE
```

`src/sys/windows/tun_dns.py`:

```python
"""DNS TUN-интерфейса на Windows. Настраивает служба (фаза 3 порта)."""

from __future__ import annotations

from src.sys.linux.tun_dns import TUN_DNS_ADDRESS
from src.sys.windows.tun_route import NO_SERVICE

__all__ = ["TUN_DNS_ADDRESS", "route_system_dns_to_tun"]


def route_system_dns_to_tun(tun_name: str) -> tuple[bool, str]:
    return False, NO_SERVICE
```

(Импорт константы из Linux-модуля временный: в фазе 3, задача 3.1, она
переезжает в `src/core/proxy_mode.py` рядом с `TUN_ADDRESS`.)

Фасады `vpn`, `resolver`, `tun_route`, `tun_dns` — Windows-ветки по образцу
задачи 1.6. `WINDOWS_READY` в `tests/test_sys_facades.py` теперь равен
`FACADES`: заменить на `WINDOWS_READY = FACADES`.

**Step 5: Run tests**

Run: `uv run pytest -q` и `python cli.py lint-all`
Expected: всё зелёное

**Step 6: Commit**

```bash
git add src/sys tests/test_sys_windows_vpn.py tests/test_sys_facades.py
git commit -m "feat(sys): интерфейсы и DNS на Windows, TUN и VPN пока с отказом"
```

---

### Task 1.12: `install_dev.sh` ставит xray.exe и wintun.dll в MSYS2

**Files:**
- Modify: `core/scripts/install_dev.sh` (`check_xray`, `download_xray`)

Тест — ручной: запуск в MSYS2 на VM (владелец) и в CI фазы 2.

**Step 1: Определение ОС**

После `XRAY_VERSION=…`:

```bash
# Закреплено вместе с xray: wintun.dll нужен ядру для TUN на Windows.
WINTUN_VERSION="0.14.1"
WINTUN_SHA256="<sha256 из задачи 1.0>"

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) XRAY_OS="windows"; XRAY_BIN="xray.exe" ;;
    *) XRAY_OS="linux"; XRAY_BIN="xray" ;;
esac
```

Если задача 1.0 ещё не выполнена, sha256 взять со страницы загрузки
https://www.wintun.net/ и записать в «Статус», откуда он взят.

**Step 2: `download_xray`**

- URL: `.../Xray-${XRAY_OS}-${ARCH}.zip` (`Xray-windows-64.zip`).
- Все упоминания файла `xray` в функции заменить на `$XRAY_BIN`; `chmod +x`
  оставить только для Linux.
- Проверить и `check_xray`: он должен вызывать `core/bin/$XRAY_BIN`.
- После распаковки xray на Windows:

```bash
download_wintun() {
    [ "$XRAY_OS" = "windows" ] || return 0
    [ -f "$PROJECT_ROOT/core/bin/wintun.dll" ] && return 0
    info "Скачивание wintun $WINTUN_VERSION..."
    local tmp
    tmp="$(mktemp -d)"
    curl -fL -o "$tmp/wintun.zip" "https://www.wintun.net/builds/wintun-${WINTUN_VERSION}.zip" \
        || error "Ошибка при скачивании wintun"
    echo "$WINTUN_SHA256  $tmp/wintun.zip" | sha256sum -c - \
        || error "Контрольная сумма wintun не совпала"
    unzip -q -o "$tmp/wintun.zip" -d "$tmp"
    cp "$tmp/wintun/bin/amd64/wintun.dll" "$PROJECT_ROOT/core/bin/"
    rm -rf "$tmp"
    success "wintun.dll установлен в core/bin"
}
```

и вызвать `download_wintun` в том месте, где вызывается `download_xray`.

Геобазы входят в архив xray для обеих ОС — проверить, что скрипт не удаляет
их после распаковки.

**Step 3: Проверка на Linux, что ничего не сломалось**

Run: `bash -n core/scripts/install_dev.sh && TENGA_TEST=1 bash core/scripts/install_dev.sh --help 2>&1 | head` (или просто `bash -n`, если у скрипта нет `--help`)
Expected: синтаксис корректен; `core/bin/xray` на машине разработчика не тронут
(скрипт видит рабочий бинарник и не скачивает).

**Step 4: Commit**

```bash
git add core/scripts/install_dev.sh
git commit -m "build: install_dev.sh ставит xray.exe и wintun.dll в MSYS2"
```

---

### Task 1.13: Ручная приёмка фазы 1 на VM (владелец проекта)

1. `git pull`, в MSYS2 UCRT64: `bash core/scripts/install_dev.sh`, затем
   `python -m pytest -q`. Ожидание: всё зелёное, тесты `windows` выполняются.
2. `python gui.py`: окно открывается, профили видны.
3. Добавить рабочий профиль, режим «системный прокси», подключиться.
   В «Параметры → Сеть и Интернет → Прокси-сервер» включён ручной прокси
   `127.0.0.1:<порт>`. Edge открывает сайты через прокси (проверить внешний IP).
4. Страница мониторинга показывает трафик (проверка задачи 1.4).
5. Отключиться: прокси в настройках Windows выключен.
6. Второй запуск `python gui.py`: окно первого выходит на передний план,
   второй процесс завершается.
7. Консольные окна при подключении и замере задержки не мигают.

Результаты — в «Статус».

---

## Статус

Код фазы выполнен на Linux (2026-10-23), задачи 1.1–1.12. Unit-тесты и lint зелёные,
`make test-gtk` зелёный. На Windows ещё ничего не запускалось: задачи 1.0 и 1.13
ждут VM владельца.

Отклонения от плана:

- **1.12, wintun.** Архив `Xray-windows-64.zip` 26.9.9 уже содержит `wintun.dll`,
  побайтно равный `wintun/bin/amd64/wintun.dll` из wintun-0.14.1 с wintun.net
  (sha256 dll `e5da8447dc2c320edc0fc52fa01885c103de8c118481f683643cacc3220dafce`).
  Отдельной загрузки wintun нет; закреплён sha256 архива xray:
  `244deaba2098c2964e49bba90df3707777e5f5f428a82d2f29604015f24beec2`.
  Скрипт распаковывает с `-n`: геобазы в `core/bin` лежат в git.
- **1.12, режим CI.** `confirm()` в `install_dev.sh`: при `CI=true` вопросов нет.
  На Windows скрипт не ставит uv (зависимости — пакеты MSYS2) и при нехватке
  пакетов предлагает `pacman -S --needed`.
- **1.9, BYPASS.** `172.2*` заменён на явный список `172.16.*`…`172.31.*`:
  маска `172.2*` захватывала и публичные `172.2.x`, `172.200.x`.
- **1.7.** Путь блокировки передаётся в `TengaApplication` параметром `lock_path`
  (через `run_app`).
- **1.5.** Тест Linux-модулей фасадов пропускается на Windows: они импортируют
  `fcntl`.

Не проверено на Windows (ждёт 1.0/1.13): unix-сокет статистики, `sockopt.interface`,
PowerShell-скрипт снимка сети, mutex и pipe активации, WinINet.
