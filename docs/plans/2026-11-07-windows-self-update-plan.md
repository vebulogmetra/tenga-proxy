# Самообновление на Windows: план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** На Windows приложение само скачивает установщик нового релиза, проверяет его, отключается, запускает установку с UAC и перезапускается новой версией.

**Architecture:** Ядро без тулкита (`src/core/app_update.py` знает ассет релиза, `src/core/app_installer.py` качает и сверяет файл), фасад `src/sys/app_install.py` запускает установщик и оставляет наблюдателя перезапуска, `AppController.install_app_update()` ведёт шаги через `Shell`, Qt-страница «О программе» показывает состояние. Дизайн — `docs/plans/2026-11-07-windows-self-update-design.md`, читать перед началом.

**Tech Stack:** Python 3.11+, requests, ctypes (`ShellExecuteExW`), PowerShell-наблюдатель, pytest, PySide6 (`make test-qt`).

**Правила проекта:** коммиты короткие, одной строкой, без co-author; `IS_WINDOWS` в `src/ui` не читать; не запускать xray с TUN, помощника и `nft` — на машине живой сеанс. Линт: `uv run ruff check src tests -q && uv run ruff format --check src tests -q`. Обычные тесты: `uv run pytest -q tests/<файл>`; Qt — `make test-qt`.

---

### Task 1: Ассет релиза в `AppRelease` и конфиге

**Files:**
- Modify: `src/core/app_update.py`
- Modify: `src/db/data_store.py:127-134`
- Test: `tests/test_core_app_update.py`

**Step 1: Напиши падающие тесты**

В конец `tests/test_core_app_update.py`:

```python
WINDOWS_ASSET = {
    "name": "veblock-0.19.0-windows-x64-setup.exe",
    "browser_download_url": (
        "https://github.com/vebulogmetra/tenga-proxy/releases/download/v0.19.0/"
        "veblock-0.19.0-windows-x64-setup.exe"
    ),
    "size": 70_000_000,
    "digest": "sha256:" + "ab" * 32,
}
WINDOWS_RELEASE = {
    "tag_name": "v0.19.0",
    "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.19.0",
    "assets": [WINDOWS_ASSET],
}


def test_windows_release_carries_the_installer_asset(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    release = select_release([WINDOWS_RELEASE], "0.18.0", architecture="AMD64")

    assert release.installable is True
    assert release.asset_url == WINDOWS_ASSET["browser_download_url"]
    assert release.asset_size == 70_000_000
    assert release.asset_digest == WINDOWS_ASSET["digest"]


@pytest.mark.parametrize(
    "patch",
    [
        {"browser_download_url": "https://evil.example/veblock-0.19.0-windows-x64-setup.exe"},
        {
            "browser_download_url": "https://github.com/vebulogmetra/tenga-proxy/releases/"
            "download/v0.18.0/veblock-0.19.0-windows-x64-setup.exe"
        },
        {
            "browser_download_url": "https://github.com/vebulogmetra/tenga-proxy/releases/"
            "download/v0.19.0/other.exe"
        },
        {"browser_download_url": WINDOWS_ASSET["browser_download_url"] + "?token=1"},
        {"digest": ""},
        {"digest": "md5:" + "ab" * 16},
        {"size": 0},
        {"size": "70000000"},
    ],
)
def test_asset_without_trusted_link_or_digest_is_not_installable(monkeypatch, patch):
    """Имя подходит, значит `has_asset`, но ставить такой файл нельзя."""
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [dict(WINDOWS_RELEASE, assets=[dict(WINDOWS_ASSET, **patch)])]

    release = select_release(payload, "0.18.0", architecture="AMD64")

    assert release.has_asset is True
    assert release.installable is False
    assert (release.asset_url, release.asset_size, release.asset_digest) == ("", 0, "")


def test_check_stores_and_clears_asset_fields(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    config = DataStore()

    check_app_update(config, "0.18.0", fetch=lambda: [WINDOWS_RELEASE], now=100)
    assert config.app_update_asset_url == WINDOWS_ASSET["browser_download_url"]
    assert config.app_update_asset_size == 70_000_000
    assert config.app_update_asset_digest == WINDOWS_ASSET["digest"]

    check_app_update(config, "0.19.0", fetch=lambda: [WINDOWS_RELEASE], now=200, force=True)
    assert (config.app_update_asset_url, config.app_update_asset_size) == ("", 0)
    assert config.app_update_asset_digest == ""
```

**Step 2: Убедись, что они падают**

Run: `uv run pytest -q tests/test_core_app_update.py`
Expected: FAIL — `AttributeError: 'AppRelease' object has no attribute 'installable'` / `DataStore` без `app_update_asset_url`.

**Step 3: Реализация**

В `src/db/data_store.py` после `app_update_has_asset: bool = False`:

```python
    # Установщик текущего релиза для самообновления: ссылка, размер, «sha256:…».
    app_update_asset_url: str = ""
    app_update_asset_size: int = 0
    app_update_asset_digest: str = ""
```

В `src/core/app_update.py`:

```python
ASSET_PREFIX = "/vebulogmetra/tenga-proxy/releases/download/"
_ASSET_NAME = re.compile(r"[A-Za-z0-9._-]+")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class AppRelease:
    version: str
    url: str
    has_asset: bool
    # Пусто, если ссылка, размер или digest ассета не прошли проверку.
    asset_url: str = ""
    asset_size: int = 0
    asset_digest: str = ""

    @property
    def installable(self) -> bool:
        return bool(self.asset_url and self.asset_size > 0 and self.asset_digest)


def safe_asset_url(url: str, tag: str, name: str) -> bool:
    """Файл релиза: только с github.com, только этого тега и этого имени."""
    if not _ASSET_NAME.fullmatch(name) or _version(tag) is None:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.netloc == "github.com"
        and not parts.query
        and not parts.fragment
        and parts.path == f"{ASSET_PREFIX}{tag}/{name}"
    )


def _asset_fields(tag: str, asset: dict | None) -> dict:
    """Ссылка, размер и digest ассета; всё пусто, если хоть что-то не проходит."""
    if asset is None:
        return {}
    name = str(asset.get("name", ""))
    url = str(asset.get("browser_download_url", ""))
    size = asset.get("size")
    digest = str(asset.get("digest", ""))
    if (
        not safe_asset_url(url, tag, name)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or not _DIGEST.fullmatch(digest)
    ):
        return {}
    return {"asset_url": url, "asset_size": size, "asset_digest": digest}
```

В `select_release` замени блок `has_asset = any(...)` и `candidates.append(...)` на:

```python
        asset = next(
            (
                asset
                for asset in assets
                if isinstance(asset, dict) and _asset_matches(str(asset.get("name", "")), aliases)
            ),
            None,
        )
        candidates.append(
            (parsed, AppRelease(version, url, asset is not None, **_asset_fields(version, asset)))
        )
```

В `check_app_update` после `config.app_update_has_asset = ...`:

```python
        config.app_update_asset_url = selected.asset_url if selected else ""
        config.app_update_asset_size = selected.asset_size if selected else 0
        config.app_update_asset_digest = selected.asset_digest if selected else ""
```

**Step 4: Тесты проходят**

Run: `uv run pytest -q tests/test_core_app_update.py tests/test_db_data_store.py 2>/dev/null || uv run pytest -q tests/test_core_app_update.py`
Expected: PASS. Также `uv run pytest -q -k "data_store or settings_form"` — PASS (новые поля со значениями по умолчанию ничего не ломают).

**Step 5: Commit**

```bash
git add src/core/app_update.py src/db/data_store.py tests/test_core_app_update.py
git commit -m "core: ссылка, размер и digest установщика в AppRelease"
```

---

### Task 2: Загрузка и проверка установщика

**Files:**
- Create: `src/core/app_installer.py`
- Test: `tests/test_core_app_installer.py`

**Step 1: Напиши падающие тесты**

`tests/test_core_app_installer.py`:

```python
"""Загрузка установщика: loopback-сервер, прокси, перенаправления, сверка, очистка."""

from __future__ import annotations

import hashlib
import http.server
import threading

import pytest
import requests

from src.core import app_installer
from src.core.app_installer import (
    InstallerCorruptError,
    InstallerDownloadError,
    download_installer,
    remove_stale_downloads,
    verify_installer,
)

PAYLOAD = bytes(range(256)) * 1024
DIGEST = "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def server():
    """/setup.exe — файл; /redirect — переход на него; /short и /long — не тот размер."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/setup.exe")
                self.end_headers()
                return
            if self.path == "/missing":
                self.send_response(404)
                self.end_headers()
                return
            body = {"/setup.exe": PAYLOAD, "/short": PAYLOAD[:-100], "/long": PAYLOAD + b"x"}[
                self.path
            ]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


def test_download_follows_redirect_checks_hash_and_reports_progress(server, tmp_path):
    seen = []

    path = download_installer(
        f"{server}/redirect",
        len(PAYLOAD),
        DIGEST,
        directory=tmp_path,
        progress=lambda done, total: seen.append((done, total)),
    )

    assert path.parent == tmp_path
    assert path.name.startswith("veblock-") and path.name.endswith("-setup.exe")
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert {total for _done, total in seen} == {len(PAYLOAD)}


@pytest.mark.parametrize(
    "route, error",
    [("/short", InstallerCorruptError), ("/long", InstallerCorruptError), ("/missing", InstallerDownloadError)],
)
def test_bad_file_is_removed(server, tmp_path, route, error):
    with pytest.raises(error):
        download_installer(f"{server}{route}", len(PAYLOAD), DIGEST, directory=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_wrong_digest_is_corrupt(server, tmp_path):
    with pytest.raises(InstallerCorruptError):
        download_installer(f"{server}/setup.exe", len(PAYLOAD), "sha256:" + "0" * 64, directory=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_connection_failure_is_a_download_error(tmp_path):
    with pytest.raises(InstallerDownloadError):
        download_installer("http://127.0.0.1:9/setup.exe", len(PAYLOAD), DIGEST, directory=tmp_path)


def test_proxy_is_tried_first_then_direct(tmp_path):
    calls = []

    def open_url(url, *, proxies):
        calls.append(proxies)
        if proxies:
            raise requests.ConnectionError("proxy down")
        return FakeResponse(200, body=PAYLOAD)

    path = download_installer(
        "https://github.com/x",
        len(PAYLOAD),
        DIGEST,
        directory=tmp_path,
        proxy_url="http://127.0.0.1:2081",
        open_url=open_url,
    )

    assert calls == [{"http": "http://127.0.0.1:2081", "https": "http://127.0.0.1:2081"}, None]
    assert path.read_bytes() == PAYLOAD


def test_redirect_to_http_is_refused(tmp_path):
    def open_url(url, *, proxies):
        return FakeResponse(302, {"Location": "http://github.com/x"})

    with pytest.raises(InstallerDownloadError, match="HTTP"):
        download_installer("https://github.com/x", len(PAYLOAD), DIGEST, directory=tmp_path, open_url=open_url)

    assert list(tmp_path.iterdir()) == []


def test_too_many_redirects_is_a_download_error(tmp_path):
    def open_url(url, *, proxies):
        return FakeResponse(302, {"Location": "https://github.com/x"})

    with pytest.raises(InstallerDownloadError, match="перенаправлений"):
        download_installer("https://github.com/x", len(PAYLOAD), DIGEST, directory=tmp_path, open_url=open_url)


def test_size_limit_rejects_huge_assets_before_the_network(tmp_path):
    def never(*_args, **_kwargs):
        pytest.fail("сеть не нужна")

    with pytest.raises(InstallerCorruptError):
        download_installer(
            "https://github.com/x",
            app_installer.MAX_INSTALLER_SIZE + 1,
            DIGEST,
            directory=tmp_path,
            open_url=never,
        )


def test_verify_installer_checks_size_then_hash(tmp_path):
    path = tmp_path / "setup.exe"
    path.write_bytes(PAYLOAD)

    verify_installer(path, len(PAYLOAD), DIGEST)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD) - 1, DIGEST)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD), "sha256:" + "0" * 64)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD), "md5:" + "0" * 32)


def test_stale_downloads_are_removed(tmp_path):
    stale = tmp_path / "veblock-old-setup.exe"
    stale.write_bytes(b"x")

    assert remove_stale_downloads(tmp_path) == [stale]
    assert not stale.exists()
    assert remove_stale_downloads(tmp_path / "missing") == []


def test_download_dir_lives_in_temp():
    assert app_installer.download_dir().name == "veblock-update"
```

**Step 2: Убедись, что они падают**

Run: `uv run pytest -q tests/test_core_app_installer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.app_installer'`.

**Step 3: Реализация**

`src/core/app_installer.py`:

```python
"""Загрузка и проверка установщика приложения. Ни тулкита, ни ОС: запуск — в src/sys."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

logger = logging.getLogger("tenga.core.app_installer")

DOWNLOAD_DIR_NAME = "veblock-update"
MAX_INSTALLER_SIZE = 512 * 1024 * 1024
MAX_REDIRECTS = 5
CHUNK_SIZE = 1 << 16
TIMEOUT = (10, 60)
_REDIRECTS = (301, 302, 303, 307, 308)

Progress = Callable[[int, int], None]


class InstallerError(Exception):
    """Обновление не установлено; приложение работает дальше."""


class InstallerDownloadError(InstallerError):
    """Сеть или сервер: «Не удалось скачать обновление»."""


class InstallerCorruptError(InstallerError):
    """Размер или SHA-256 не совпали: «Файл повреждён, попробуйте позже»."""


class InstallCancelled(InstallerError):
    """Пользователь отказал в UAC: «Установка отменена»."""


def download_dir() -> Path:
    return Path(tempfile.gettempdir()) / DOWNLOAD_DIR_NAME


def remove_stale_downloads(directory: Path | None = None) -> list[Path]:
    """Удалить всё из каталога загрузок: при старте загрузка идти не может."""
    directory = download_dir() if directory is None else directory
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    for path in directory.iterdir():
        try:
            if path.is_file():
                path.unlink()
                removed.append(path)
        except OSError as e:
            logger.warning("Cannot remove %s: %s", path, e)
    return removed


def _open(url: str, *, proxies: dict | None):
    """Потоковый ответ без автоматических перенаправлений; пул живёт при ответе."""
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url, stream=True, allow_redirects=False, timeout=TIMEOUT, proxies=proxies or {}
        )
    except Exception:
        session.close()
        raise
    response._owner_session = session
    return response


def _close(response) -> None:
    response.close()
    owner = getattr(response, "_owner_session", None)
    if owner is not None:
        owner.close()


def _fetch(url: str, proxies: dict | None, open_url):
    """Ответ с телом файла; перенаправления только без понижения до HTTP."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        response = open_url(current, proxies=proxies)
        if response.status_code not in _REDIRECTS:
            if response.status_code != 200:
                _close(response)
                raise InstallerDownloadError(f"HTTP {response.status_code}")
            return response
        target = urljoin(current, response.headers.get("Location", ""))
        _close(response)
        if urlsplit(current).scheme == "https" and urlsplit(target).scheme != "https":
            raise InstallerDownloadError("Перенаправление с HTTPS на HTTP")
        current = target
    raise InstallerDownloadError("Слишком много перенаправлений")


def _fetch_via_proxy_or_direct(url: str, proxy_url: str | None, open_url):
    # Сначала через работающий прокси: GitHub напрямую бывает закрыт.
    if proxy_url:
        try:
            return _fetch(url, {"http": proxy_url, "https": proxy_url}, open_url)
        except (requests.RequestException, InstallerDownloadError) as e:
            logger.warning(
                "Download through the proxy failed (%s), trying directly", type(e).__name__
            )
    return _fetch(url, None, open_url)


def _save(response, fd: int, size: int, progress: Progress | None) -> None:
    done = 0
    with os.fdopen(fd, "wb") as out:
        try:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                done += len(chunk)
                if done > size:
                    raise InstallerCorruptError("Файл больше заявленного")
                out.write(chunk)
                if progress is not None:
                    progress(done, size)
        except requests.RequestException as e:
            raise InstallerDownloadError(type(e).__name__) from e


def download_installer(
    url: str,
    size: int,
    digest: str,
    *,
    proxy_url: str | None = None,
    progress: Progress | None = None,
    directory: Path | None = None,
    open_url=_open,
) -> Path:
    """Скачать установщик в каталог загрузок и сверить размер и SHA-256.

    Файл получает уникальное имя и удаляется при любой ошибке. `size` и
    `digest` — из ответа API релизов, им и верим.
    """
    if size <= 0 or size > MAX_INSTALLER_SIZE:
        raise InstallerCorruptError(f"Недопустимый размер установщика: {size}")
    directory = download_dir() if directory is None else directory
    directory.mkdir(parents=True, exist_ok=True)
    try:
        response = _fetch_via_proxy_or_direct(url, proxy_url, open_url)
    except requests.RequestException as e:
        raise InstallerDownloadError(type(e).__name__) from e
    fd, name = tempfile.mkstemp(prefix="veblock-", suffix="-setup.exe", dir=directory)
    path = Path(name)
    try:
        try:
            _save(response, fd, size, progress)
        finally:
            _close(response)
        verify_installer(path, size, digest)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def verify_installer(path: Path, size: int, digest: str) -> None:
    """Размер и SHA-256 файла должны совпасть с ответом API."""
    if not digest.startswith("sha256:"):
        raise InstallerCorruptError("Неизвестный алгоритм контрольной суммы")
    if path.stat().st_size != size:
        raise InstallerCorruptError("Размер файла не совпадает")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            sha.update(block)
    if sha.hexdigest() != digest[len("sha256:") :]:
        raise InstallerCorruptError("Контрольная сумма не совпадает")
```

**Step 4: Тесты проходят**

Run: `uv run pytest -q tests/test_core_app_installer.py`
Expected: PASS (13 тестов).

**Step 5: Commit**

```bash
git add src/core/app_installer.py tests/test_core_app_installer.py
git commit -m "core: загрузка и сверка установщика приложения"
```

---

### Task 3: Фасад `src/sys/app_install.py`

**Files:**
- Create: `src/sys/app_install.py`, `src/sys/linux/app_install.py`, `src/sys/windows/app_install.py`
- Modify: `tests/test_sys_facades.py:11-21` (список `FACADES`)
- Test: `tests/test_sys_app_install.py`

**Step 1: Напиши падающие тесты**

В `tests/test_sys_facades.py` добавь `"app_install",` в конец списка `FACADES`.

`tests/test_sys_app_install.py`:

```python
"""Запуск установщика: UAC через подменённый runas, наблюдатель перезапуска."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.app_installer import InstallCancelled
from src.sys.linux import app_install as linux_install
from src.sys.windows import app_install

INSTALLER_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


def test_linux_never_self_updates():
    assert linux_install.can_self_update() is False
    with pytest.raises(NotImplementedError):
        linux_install.launch_installer(Path("setup.exe"))


def test_windows_self_update_needs_the_frozen_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_install.can_self_update() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert app_install.can_self_update() is True


def test_launch_runs_the_installer_silently_and_leaves_a_relaunch_watcher():
    calls = []

    app_install.launch_installer(
        Path(r"C:\tmp\veblock-setup.exe"),
        runas=lambda path, args: calls.append(("runas", path, args)) or 4242,
        spawn=lambda command: calls.append(("spawn", command)),
        executable=r"C:\Program Files\Veblock\tenga-proxy.exe",
    )

    assert calls[0] == ("runas", r"C:\tmp\veblock-setup.exe", INSTALLER_ARGS)
    kind, command = calls[1]
    assert kind == "spawn"
    assert command[:5] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden"]
    assert "Get-Process -Id 4242" in command[-1]
    assert "Start-Process -FilePath 'C:\\Program Files\\Veblock\\tenga-proxy.exe'" in command[-1]


def test_uac_refusal_leaves_no_watcher():
    def refuse(_path, _args):
        raise InstallCancelled("нет")

    spawned = []
    with pytest.raises(InstallCancelled):
        app_install.launch_installer(Path("setup.exe"), runas=refuse, spawn=spawned.append)

    assert spawned == []


def test_relaunch_command_escapes_single_quotes():
    command = app_install.relaunch_command(7, "C:\\O'Neil\\app.exe")

    assert "'C:\\O''Neil\\app.exe'" in command[-1]
```

**Step 2: Убедись, что они падают**

Run: `uv run pytest -q tests/test_sys_app_install.py tests/test_sys_facades.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.sys.linux.app_install'`.

**Step 3: Реализация**

`src/sys/app_install.py`:

```python
"""Самообновление приложения: можно ли и как запустить скачанный установщик."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.app_install import can_self_update, launch_installer
else:
    from src.sys.linux.app_install import can_self_update, launch_installer

__all__ = ["can_self_update", "launch_installer"]
```

`src/sys/linux/app_install.py`:

```python
"""На Linux приложение ставится пакетом: самообновления нет."""

from __future__ import annotations

from pathlib import Path


def can_self_update() -> bool:
    return False


def launch_installer(path: Path) -> None:
    raise NotImplementedError("Самообновление доступно только на Windows")
```

`src/sys/windows/app_install.py`:

```python
"""Запуск установщика Inno Setup с UAC и перезапуск приложения после него.

Перезапуск делает скрытый PowerShell от имени пользователя: пункт `[Run]` с
`runasoriginaluser` у установщика, запущенного через `runas`, стартовал бы
новую версию с повышенными правами. См.
docs/plans/2026-11-07-windows-self-update-design.md.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from src.core.app_installer import InstallCancelled
from src.core.platform_info import no_window

logger = logging.getLogger("tenga.sys.app_install")

INSTALLER_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1


def can_self_update() -> bool:
    """Только собранное приложение: из исходников установщик ставить некуда."""
    return bool(getattr(sys, "frozen", False))


def relaunch_command(installer_pid: int, executable: str) -> list[str]:
    """PowerShell ждёт выхода установщика и запускает приложение от пользователя.

    `Get-Process -Id` видит процесс любого пользователя: установщик могли
    поднять под другой учётной записью администратора.
    """
    quoted = executable.replace("'", "''")
    script = (
        f"while (Get-Process -Id {int(installer_pid)} -ErrorAction SilentlyContinue) "
        "{ Start-Sleep -Milliseconds 500 }; "
        f"Start-Process -FilePath '{quoted}'"
    )
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-Command",
        script,
    ]


def _runas(path: str, parameters: str) -> int:
    """ShellExecuteExW с глаголом runas; возвращает PID установщика."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = path
    info.lpParameters = parameters
    info.nShow = SW_SHOWNORMAL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise InstallCancelled("Пользователь отказал в UAC")
        raise OSError(error, "ShellExecuteExW failed")
    try:
        return int(kernel32.GetProcessId(info.hProcess))
    finally:
        kernel32.CloseHandle(info.hProcess)


def _spawn(command: list[str]) -> None:
    # Без наследования дескрипторов и окна: наблюдатель переживает выход приложения.
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **no_window(),
    )


def launch_installer(
    path: Path,
    *,
    runas: Callable[[str, str], int] = _runas,
    spawn: Callable[[list[str]], None] = _spawn,
    executable: str | None = None,
) -> None:
    """Запустить установщик с UAC и оставить наблюдателя перезапуска.

    Отказ в UAC — `InstallCancelled`, приложение работает дальше. После
    успеха вызывающий код выходит сам.
    """
    pid = runas(str(path), INSTALLER_ARGS)
    logger.info("Installer started, pid %s", pid)
    spawn(relaunch_command(pid, executable or sys.executable))
```

**Step 4: Тесты проходят**

Run: `uv run pytest -q tests/test_sys_app_install.py tests/test_sys_facades.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/sys/app_install.py src/sys/linux/app_install.py src/sys/windows/app_install.py tests/test_sys_app_install.py tests/test_sys_facades.py
git commit -m "sys: запуск установщика с UAC и наблюдатель перезапуска"
```

---

### Task 4: Очистка каталога загрузок при старте

**Files:**
- Modify: `gui.py:116-134` (рядом с `cleanup_legacy_install`) и `gui.py:255-257`
- Test: `tests/test_gui_entrypoint.py`

**Step 1: Напиши падающий тест**

После `test_legacy_cleanup_never_blocks_the_start` в `tests/test_gui_entrypoint.py`:

```python
def test_update_downloads_are_removed_at_start(entry, monkeypatch, tmp_path):
    from src.core import app_installer

    stale = tmp_path / "veblock-old-setup.exe"
    stale.write_bytes(b"x")
    monkeypatch.setattr(app_installer, "download_dir", lambda: tmp_path)

    entry.cleanup_update_downloads()

    assert not stale.exists()


def test_update_cleanup_never_blocks_the_start(entry, monkeypatch):
    def boom(_directory=None):
        raise PermissionError("read-only temp")

    monkeypatch.setattr("src.core.app_installer.remove_stale_downloads", boom)

    entry.cleanup_update_downloads()
```

**Step 2: Убедись, что они падают**

Run: `uv run pytest -q tests/test_gui_entrypoint.py -k update`
Expected: FAIL — `AttributeError: module 'gui_entry' has no attribute 'cleanup_update_downloads'`.

**Step 3: Реализация**

В `gui.py` после `cleanup_legacy_install`:

```python
def cleanup_update_downloads() -> None:
    """Убрать установщики прошлых самообновлений: при старте загрузка идти не может."""
    from src.core.app_installer import remove_stale_downloads

    log = logging.getLogger("startup")
    try:
        removed = remove_stale_downloads()
    except Exception:
        log.exception("Failed to remove update downloads")
        return
    for path in removed:
        log.info("Removed update download %s", path)
```

В `main()`:

```python
    if holds_lock:
        recover_network()
        cleanup_legacy_install()
        cleanup_update_downloads()
```

**Step 4: Тесты проходят**

Run: `uv run pytest -q tests/test_gui_entrypoint.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add gui.py tests/test_gui_entrypoint.py
git commit -m "gui: чистить каталог загрузок обновления при старте"
```

---

### Task 5: `Shell.refresh_app_update()` и `Shell.quit()`

**Files:**
- Modify: `src/ui/controller.py:67-130` (протокол `Shell`)
- Modify: `src/ui/application.py:65-160` (`_GtkShell`)
- Modify: `src/ui/qt/application.py:70-150` (`_QtShell`)
- Modify: `src/ui/qt/dialogs/settings.py:721-730` (`SettingsDialog.refresh`)
- Modify: `tests/test_ui_controller.py:42-110` (`FakeShell`)

**Step 1: Напиши падающий тест**

В `tests/test_ui_qt_application.py` после `test_toast_button_runs_its_action`:

```python
def test_shell_quit_stops_the_event_loop(made, monkeypatch):
    app, _service = made
    seen = []
    monkeypatch.setattr(app.qt, "quit", lambda: seen.append("quit"))

    app.controller._shell.quit()

    assert seen == ["quit"]
```

**Step 2: Убедись, что он падает**

Run: `make test-qt QT_TESTS="tests/test_ui_qt_application.py -k shell_quit"`
Expected: FAIL — `AttributeError: '_QtShell' object has no attribute 'quit'`.

**Step 3: Реализация**

В протокол `Shell` (`src/ui/controller.py`) после `open_settings_section`:

```python
    def refresh_app_update(self) -> None:
        """Состояние самообновления изменилось: подпись и кнопка в «О программе»."""

    def quit(self) -> None:
        """Штатный выход: ядро гасится, блокировка снимается."""
```

В `FakeShell` (`tests/test_ui_controller.py`):

```python
    def refresh_app_update(self):
        self.calls.append(("refresh_app_update",))

    def quit(self):
        self.calls.append(("quit",))
```

В `_GtkShell` (`src/ui/application.py`), после `open_settings_section`:

```python
    def refresh_app_update(self) -> None:
        """GTK самообновления не предлагает: в «О программе» показывать нечего."""

    def quit(self) -> None:
        self._app.quit()
```

В `_QtShell` (`src/ui/qt/application.py`), там же:

```python
    def refresh_app_update(self) -> None:
        self._app.refresh_dialog()

    def quit(self) -> None:
        self._app.quit()
```

В `SettingsDialog.refresh` (`src/ui/qt/dialogs/settings.py`) первой строкой тела после импорта: `self.about.refresh_app_update()` — метод появится в Task 8; до него добавь на `AboutPage` заглушку:

```python
    def refresh_app_update(self) -> None:
        """Заполняется в Task 8."""
```

**Step 4: Тесты проходят**

Run: `make test-qt` и `uv run pytest -q tests/test_ui_controller.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ui/controller.py src/ui/application.py src/ui/qt/application.py src/ui/qt/dialogs/settings.py src/ui/qt/dialogs/settings_pages.py tests/test_ui_controller.py tests/test_ui_qt_application.py
git commit -m "ui: Shell.quit и refresh_app_update"
```

---

### Task 6: `AppController.install_app_update()`

**Files:**
- Modify: `src/ui/controller.py` (константы, `AppUpdateStatus`, конструктор, `disconnect_proxy`, `refresh_app_releases_if_due`, новые методы)
- Test: `tests/test_ui_controller.py`

**Step 1: Напиши падающие тесты**

В импорт из `src.ui.controller` в начале `tests/test_ui_controller.py` добавь `APP_UPDATE_UNAVAILABLE, AppUpdateStatus, CONFIRM_APP_UPDATE`. В раздел `# --- обновления и ссылки ---`:

```python
EXE = b"exe"


def _installable(config):
    config.app_update_target = "v0.19.0"
    config.app_update_has_asset = True
    config.app_update_asset_url = (
        "https://github.com/vebulogmetra/tenga-proxy/releases/download/v0.19.0/"
        "veblock-0.19.0-windows-x64-setup.exe"
    )
    config.app_update_asset_size = len(EXE)
    config.app_update_asset_digest = "sha256:" + hashlib.sha256(EXE).hexdigest()


def _self_updating(tmp_path, **kwargs):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    shell = FakeShell()
    controller = AppController(
        context, shell, ImmediateLoop(), can_self_update=lambda: True, **kwargs
    )
    _installable(context.config)
    return controller, shell, context


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _fake_download(tmp_path, monkeypatch, *, error=None):
    def download(url, size, digest, *, proxy_url=None, progress=None, directory=None, **_kw):
        if error is not None:
            raise error
        path = tmp_path / "veblock-test-setup.exe"
        path.write_bytes(EXE)
        progress(len(EXE), len(EXE))
        return path

    monkeypatch.setattr("src.core.app_installer.download_installer", download)


def test_install_is_refused_without_an_installer(made):
    controller, shell, _ = made

    controller.install_app_update()

    assert shell.confirms == []
    assert shell.last_toast == APP_UPDATE_UNAVAILABLE


def test_install_asks_for_confirmation_first(tmp_path):
    controller, shell, _context = _self_updating(tmp_path)

    controller.install_app_update()

    (confirm,) = shell.confirms
    assert confirm.kind == CONFIRM_APP_UPDATE
    assert confirm.body == (
        "Будет установлена версия v0.19.0. Подключение прервётся, приложение перезапустится"
    )
    assert confirm.confirm_label == "Обновить"
    assert controller.app_install_thread is None


def test_install_downloads_disconnects_launches_and_quits(tmp_path, monkeypatch):
    launched = []
    controller, shell, context = _self_updating(tmp_path, launch_installer=launched.append)
    _fake_download(tmp_path, monkeypatch)
    calls = []
    controller.set_connection_service(FakeService(calls))
    context.proxy_state.set_running(1, "system_proxy")

    controller.install_app_update()
    shell.confirms[0].on_confirm()
    _wait_for(lambda: ("quit",) in shell.calls)

    assert calls == [("disconnect",)]
    assert launched == [tmp_path / "veblock-test-setup.exe"]
    assert controller.app_update_status == AppUpdateStatus("Установка…", busy=True)
    assert shell.enabled["install-app-update"] is False
    assert "Загрузка… 100 %" in [text for text, _b, _a in shell.toasts] or any(
        call == ("refresh_app_update",) for call in shell.calls
    )


def test_install_skips_disconnect_when_not_connected(tmp_path, monkeypatch):
    launched = []
    controller, shell, _context = _self_updating(tmp_path, launch_installer=launched.append)
    _fake_download(tmp_path, monkeypatch)
    calls = []
    controller.set_connection_service(FakeService(calls))

    controller.install_app_update()
    shell.confirms[0].on_confirm()
    _wait_for(lambda: ("quit",) in shell.calls)

    assert calls == []
    assert len(launched) == 1


def test_second_install_is_refused_while_busy(tmp_path, monkeypatch):
    controller, shell, _context = _self_updating(tmp_path)
    controller._set_app_update_status("Загрузка… 10 %", busy=True)

    controller.install_app_update()

    assert shell.confirms == []
    assert shell.last_toast == "Обновление уже идёт"


@pytest.mark.parametrize(
    "error, text",
    [
        (InstallerCorruptError("hash"), "Файл повреждён, попробуйте позже"),
        (InstallerDownloadError("net"), "Не удалось скачать обновление"),
    ],
)
def test_failed_download_is_reported_in_label_and_toast(tmp_path, monkeypatch, error, text):
    controller, shell, _context = _self_updating(tmp_path)
    _fake_download(tmp_path, monkeypatch, error=error)

    controller.install_app_update()
    shell.confirms[0].on_confirm()
    controller.app_install_thread.join(5)

    assert controller.app_update_status == AppUpdateStatus(text, busy=False)
    assert shell.last_toast == text
    assert shell.enabled["install-app-update"] is True
    assert ("quit",) not in shell.calls


def test_uac_refusal_keeps_the_app_running_and_removes_the_file(tmp_path, monkeypatch):
    def refuse(_path):
        raise InstallCancelled("нет")

    controller, shell, _context = _self_updating(tmp_path, launch_installer=refuse)
    _fake_download(tmp_path, monkeypatch)

    controller.install_app_update()
    shell.confirms[0].on_confirm()
    _wait_for(lambda: controller.app_update_status.text == "Установка отменена")

    assert controller.app_update_status.busy is False
    assert shell.last_toast == "Установка отменена"
    assert ("quit",) not in shell.calls
    assert not (tmp_path / "veblock-test-setup.exe").exists()


def test_tampered_file_is_not_launched(tmp_path, monkeypatch):
    launched = []
    controller, shell, context = _self_updating(tmp_path, launch_installer=launched.append)
    _fake_download(tmp_path, monkeypatch)
    # Файл подменили между загрузкой и запуском: хеш в конфиге уже другой.
    context.config.app_update_asset_digest = "sha256:" + "0" * 64

    controller.install_app_update()
    shell.confirms[0].on_confirm()
    _wait_for(lambda: controller.app_update_status.text == "Файл повреждён, попробуйте позже")

    assert launched == []
    assert ("quit",) not in shell.calls


def test_daily_check_offers_the_update_button(tmp_path, monkeypatch):
    from src.core import platform_info
    from tests.test_core_app_update import WINDOWS_RELEASE

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    controller = AppController(
        context, shell, ImmediateLoop(), app_version=lambda: "0.18.0", can_self_update=lambda: True
    )
    controller.set_app_release_fetcher(lambda: [WINDOWS_RELEASE])

    controller.refresh_app_releases_if_due()
    controller.app_update_thread.join(5)

    assert shell.toasts[-1] == ("Доступна версия v0.19.0", "Обновить", "app.install-app-update")
```

Добавь в импорты файла `import hashlib`, `import time` и `from src.core.app_installer import InstallCancelled, InstallerCorruptError, InstallerDownloadError`. Поле `enabled` у `FakeShell` уже есть (`set_action_enabled` пишет в него).

**Step 2: Убедись, что они падают**

Run: `uv run pytest -q tests/test_ui_controller.py -k "install or daily_check"`
Expected: FAIL — `ImportError: cannot import name 'APP_UPDATE_UNAVAILABLE'`.

**Step 3: Реализация**

В `src/ui/controller.py`:

Импорты: `from pathlib import Path` (если нет), `from src.sys.app_install import can_self_update, launch_installer` рядом с остальными `from src.` импортами.

Константы после `CONFIRM_URL_CHANGE`:

```python
CONFIRM_APP_UPDATE = "app-update"
APP_UPDATE_UNAVAILABLE = "Установщик недоступен, обновите вручную со страницы проекта"
APP_UPDATE_DOWNLOAD_FAILED = "Не удалось скачать обновление"
APP_UPDATE_CORRUPT = "Файл повреждён, попробуйте позже"
APP_UPDATE_CANCELLED = "Установка отменена"
APP_UPDATE_LAUNCH_FAILED = "Не удалось запустить установщик"
```

Датакласс рядом с другими датаклассами модуля:

```python
@dataclass(frozen=True)
class AppUpdateStatus:
    """Что «О программе» показывает о ходе самообновления; пустой текст — ничего не идёт."""

    text: str = ""
    busy: bool = False
```

Конструктор — два новых keyword-параметра после `app_version`:

```python
        can_self_update: Callable[[], bool] = can_self_update,
        launch_installer: Callable[[Path], None] = launch_installer,
```

и в теле:

```python
        self._can_self_update = can_self_update
        self._launch_installer = launch_installer
        self.app_update_status = AppUpdateStatus()
        self.app_install_thread = None
```

`disconnect_proxy` — параметр `then`:

```python
    def disconnect_proxy(self, then: Callable[[], None] | None = None) -> None:
        """Stop the proxy in the background; `then` — после завершения, удачного или нет."""
        if self.connection_busy():
            self.toast("Подключение уже выполняется")
            return

        def done(result) -> None:
            self._on_disconnection_done(result)
            if then is not None:
                then()

        def failed(error: BaseException) -> None:
            self._on_connection_failed(error)
            if then is not None:
                then()

        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            service.disconnect,
            on_done=done,
            on_error=failed,
            dispatch=self._loop.dispatch,
            name="tenga-disconnect",
        )
```

В `refresh_app_releases_if_due.done`:

```python
        def done(release):
            if release and config.app_update_notified != release.version:
                if self.can_self_update() and release.installable:
                    self.toast(
                        f"Доступна версия {release.version}",
                        button="Обновить",
                        action="app.install-app-update",
                    )
                else:
                    self.toast(
                        f"Доступна версия {release.version}. Откройте настройки → О программе"
                    )
                config.app_update_notified = release.version
            context.save_config()
```

Новый раздел после `refresh_app_releases_if_due`:

```python
    # --- самообновление ---

    def can_self_update(self) -> bool:
        return self._can_self_update()

    def app_update_installable(self) -> bool:
        """Известен установщик с контрольной суммой, и его можно поставить отсюда."""
        config = self.context.config
        return bool(
            self.can_self_update()
            and config.app_update_target
            and config.app_update_asset_url
            and config.app_update_asset_size > 0
            and config.app_update_asset_digest
        )

    def _set_app_update_status(self, text: str, *, busy: bool) -> None:
        self.app_update_status = AppUpdateStatus(text, busy)
        self._shell.set_action_enabled("install-app-update", not busy)
        self._shell.refresh_app_update()

    def _fail_app_update(self, text: str) -> None:
        # И в подпись, и тостом: установку могли начать из тоста при закрытых настройках.
        self._set_app_update_status(text, busy=False)
        self.toast(text)

    def install_app_update(self) -> None:
        """Скачать установщик, отключиться, запустить его с UAC и выйти."""
        if self.app_update_status.busy:
            self.toast("Обновление уже идёт")
            return
        if not self.app_update_installable():
            self.toast(APP_UPDATE_UNAVAILABLE)
            return
        version = self.context.config.app_update_target
        self._shell.confirm(
            CONFIRM_APP_UPDATE,
            f"Обновить {__app_name__}?",
            f"Будет установлена версия {version}. "
            "Подключение прервётся, приложение перезапустится",
            self._download_app_update,
            confirm_label="Обновить",
        )

    def _show_download_progress(self, percent: int) -> None:
        self._set_app_update_status(f"Загрузка… {percent} %", busy=True)

    def _download_app_update(self) -> None:
        from src.core.app_installer import InstallerCorruptError, download_installer
        from src.sub.route import local_proxy_url

        context = self.context
        config = context.config
        url = config.app_update_asset_url
        size = config.app_update_asset_size
        digest = config.app_update_asset_digest
        self._show_download_progress(0)
        shown = [0]

        def progress(done: int, total: int) -> None:
            # Из рабочего потока: в главный уходят только целые проценты.
            percent = done * 100 // total
            if percent != shown[0]:
                shown[0] = percent
                self._loop.dispatch(self._show_download_progress, percent)

        def work():
            # Загрузка при живом подключении: GitHub напрямую бывает закрыт.
            return download_installer(
                url,
                size,
                digest,
                proxy_url=local_proxy_url(config, context.proxy_state),
                progress=progress,
            )

        def done(path) -> None:
            if self.connection_busy():
                self._fail_app_update("Подключение ещё выполняется, повторите позже")
                return
            if context.proxy_state.is_running:
                self._set_app_update_status("Отключение…", busy=True)
                self.disconnect_proxy(then=lambda: self._launch_app_update(path))
            else:
                self._launch_app_update(path)

        def failed(error: BaseException) -> None:
            self._fail_app_update(
                APP_UPDATE_CORRUPT
                if isinstance(error, InstallerCorruptError)
                else APP_UPDATE_DOWNLOAD_FAILED
            )

        self.app_install_thread = run_in_background(
            work,
            on_done=done,
            on_error=failed,
            dispatch=self._loop.dispatch,
            name="tenga-app-install",
        )

    def _launch_app_update(self, path: Path) -> None:
        from src.core.app_installer import InstallCancelled, InstallerCorruptError, verify_installer

        config = self.context.config
        size, digest = config.app_update_asset_size, config.app_update_asset_digest
        self._set_app_update_status("Установка…", busy=True)

        def work() -> None:
            # Хеш ещё раз перед запуском: файл лежал в каталоге, доступном пользователю.
            verify_installer(path, size, digest)
            self._launch_installer(path)

        def done(_result) -> None:
            # Дальше установщик: он остановит службу и заменит файлы, наблюдатель
            # перезапустит приложение.
            self._shell.quit()

        def failed(error: BaseException) -> None:
            Path(path).unlink(missing_ok=True)
            if isinstance(error, InstallCancelled):
                self._fail_app_update(APP_UPDATE_CANCELLED)
            elif isinstance(error, InstallerCorruptError):
                self._fail_app_update(APP_UPDATE_CORRUPT)
            else:
                self._fail_app_update(APP_UPDATE_LAUNCH_FAILED)

        self.app_install_thread = run_in_background(
            work,
            on_done=done,
            on_error=failed,
            dispatch=self._loop.dispatch,
            name="tenga-app-launch",
        )
```

**Step 4: Тесты проходят**

Run: `uv run pytest -q tests/test_ui_controller.py`
Expected: PASS. Если `test_install_downloads_disconnects_launches_and_quits` падает на последнем `assert` — упрости его до `assert ("refresh_app_update",) in shell.calls`.

**Step 5: Commit**

```bash
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "ui: установка обновления из контроллера"
```

---

### Task 7: Действие `install-app-update` в обоих интерфейсах

**Files:**
- Modify: `src/ui/application.py:270-300` (`handlers`)
- Modify: `src/ui/qt/application.py:215-240` (`handlers`)
- Test: `tests/test_ui_qt_application.py`, `tests/test_ui_window.py`

**Step 1: Напиши падающие тесты**

В `tests/test_ui_qt_application.py`:

```python
def test_install_action_reaches_the_controller(made, monkeypatch):
    app, _service = made
    seen = []
    monkeypatch.setattr(app.controller, "install_app_update", lambda: seen.append(1))

    app.activate_action("install-app-update")

    assert seen == [1]
```

В `tests/test_ui_window.py` (фикстура `adw_app` из `tests/conftest.py` — приложение GTK на временном каталоге настроек):

```python
def test_install_action_is_registered(adw_app):
    assert adw_app.lookup_action("install-app-update") is not None
```

**Step 2: Убедись, что они падают**

Run: `make test-qt` и `make test-gtk`
Expected: FAIL — Qt: `Unknown action install-app-update` в логе и `seen == []`; GTK: `lookup_action` возвращает `None`.

**Step 3: Реализация**

В обоих словарях `handlers` после `"release-block": ...`:

```python
            "install-app-update": lambda: self.controller.install_app_update(),
```

**Step 4: Тесты проходят**

Run: `make test-qt && make test-gtk`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ui/application.py src/ui/qt/application.py tests/test_ui_qt_application.py tests/test_ui_window.py
git commit -m "ui: действие install-app-update"
```

---

### Task 8: Qt «О программе»: «Обновить…» вместо «Открыть релиз»

**Files:**
- Modify: `src/ui/qt/dialogs/settings_pages.py:220-330` (`AboutPage`)
- Test: `tests/test_ui_qt_settings.py`

**Step 1: Напиши падающие тесты**

В `tests/test_ui_qt_settings.py` после `test_app_update_check_without_releases`:

```python
RELEASE_PAGE = "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.19.0"
UNAVAILABLE = "Доступна версия v0.19.0. Установщик недоступен, обновите вручную со страницы проекта"


def _installable(config):
    config.app_update_target = "v0.19.0"
    config.app_update_url = RELEASE_PAGE
    config.app_update_has_asset = True
    config.app_update_asset_url = (
        "https://github.com/vebulogmetra/tenga-proxy/releases/download/v0.19.0/"
        "veblock-0.19.0-windows-x64-setup.exe"
    )
    config.app_update_asset_size = 3
    config.app_update_asset_digest = "sha256:" + "ab" * 32


def test_about_offers_the_release_page_without_self_update(app):
    _installable(app.context.config)

    about = _open(app).about

    assert about.app_update_button.text() == "Открыть релиз"
    assert about.app_update_button.isEnabled()
    assert about.app_update_label.text() == "Доступна версия v0.19.0"


def test_about_offers_install_when_self_update_is_possible(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    seen = []
    app._handlers["install-app-update"] = lambda _target: seen.append(1)

    about = _open(app).about
    about.app_update_button.click()

    assert about.app_update_button.text() == "Обновить…"
    assert seen == [1]


def test_about_disables_install_without_a_digest(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    app.context.config.app_update_asset_digest = ""

    about = _open(app).about

    assert not about.app_update_button.isEnabled()
    assert about.app_update_label.text() == UNAVAILABLE


def test_about_shows_install_progress_from_the_controller(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    about = _open(app).about

    app.controller._set_app_update_status("Загрузка… 42 %", busy=True)

    assert about.app_update_label.text() == "Загрузка… 42 %"
    assert not about.app_update_button.isEnabled()


def test_manual_check_reports_a_release_without_installer(app, monkeypatch):
    """Ручная проверка идёт с настоящей версией приложения: релиз заведомо новее."""
    from src.core import platform_info
    from tests.test_core_app_update import WINDOWS_ASSET

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    about = _open(app).about
    about.fetch_app_releases = lambda: [
        {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v99.0.0",
            "assets": [dict(WINDOWS_ASSET, digest="")],
        }
    ]

    about.check_app_update()
    about.app_update_thread.join(5)
    wait_until(lambda: about.app_check_button.isEnabled())

    assert about.app_update_label.text() == UNAVAILABLE.replace("v0.19.0", "v99.0.0")
    assert not about.app_update_button.isEnabled()
```

**Step 2: Убедись, что они падают**

Run: `make test-qt`
Expected: FAIL — `AttributeError: 'AboutPage' object has no attribute 'app_update_button'`.

**Step 3: Реализация**

В `src/ui/qt/dialogs/settings_pages.py` дополни строку `from src.ui.controller import CONFIRM_DELETE` до `from src.ui.controller import APP_UPDATE_UNAVAILABLE, CONFIRM_DELETE`.

В `AboutPage.__init__` замени строки с `app_release_button` на:

```python
        self._controller = self._app.controller
        self.app_update_label = QLabel(self._release_text())
        self.app_check_button = QPushButton("Проверить")
        self.app_check_button.clicked.connect(self.check_app_update)
        # Там, где самообновления нет (Qt на Linux), кнопка по-прежнему открывает релиз.
        self.app_update_button = QPushButton(
            "Обновить…" if self._controller.can_self_update() else "Открыть релиз"
        )
        self.app_update_button.clicked.connect(self._on_update_clicked)
        form.addRow(
            "Обновление приложения",
            self._with(self.app_update_label, self.app_check_button, self.app_update_button),
        )
        self.refresh_app_update()
```

(удали старую строку `self.app_update_label = QLabel(self._config.app_update_target or ...)`).

Методы раздела `# --- обновление приложения ---`:

```python
    def _release_text(self) -> str:
        """Подпись по сведениям в конфиге; ход установки её перекрывает."""
        config = self._config
        if not config.app_update_target:
            return "Нет сведений о новой версии"
        text = f"Доступна версия {config.app_update_target}"
        if not config.app_update_has_asset:
            return text + "; " + platform_texts.missing_release_asset()
        if self._controller.can_self_update() and not self._controller.app_update_installable():
            return text + ". " + APP_UPDATE_UNAVAILABLE
        return text

    def refresh_app_update(self) -> None:
        """Состояние контроллера: подпись хода установки и доступность кнопки."""
        status = self._controller.app_update_status
        if status.text:
            self.app_update_label.setText(status.text)
        self._refresh_update_button()

    def _refresh_update_button(self) -> None:
        controller = self._controller
        if controller.can_self_update():
            enabled = controller.app_update_installable() and not controller.app_update_status.busy
        else:
            enabled = bool(self._config.app_update_url)
        self.app_update_button.setEnabled(enabled)

    def _on_update_clicked(self) -> None:
        if self._controller.can_self_update():
            self._app.activate_action("install-app-update")
        else:
            self._open_app_release()
```

В `check_app_update.done` замени тело на:

```python
        def done(release) -> None:
            self.app_check_button.setEnabled(True)
            context.save_config()
            if release is None:
                self.app_update_label.setText("Новых версий нет")
            else:
                self.app_update_label.setText(self._release_text())
            self._refresh_update_button()
```

(`check_app_update` уже записал `app_update_*` в конфиг, поэтому `_release_text()` видит свежие данные.) Убери заглушку `refresh_app_update` из Task 5.

**Step 4: Тесты проходят**

Run: `make test-qt`
Expected: PASS, включая прежний `test_app_update_check_without_releases`.

**Step 5: Commit**

```bash
git add src/ui/qt/dialogs/settings_pages.py tests/test_ui_qt_settings.py
git commit -m "qt: кнопка «Обновить…» в «О программе»"
```

---

### Task 9: Документация и полная проверка

**Files:**
- Modify: `CLAUDE.md` (раздел Architecture, после абзаца «Отличия UI по ОС»)

**Step 1: Абзац в CLAUDE.md**

```markdown
**Самообновление на Windows** - `src/core/app_update.py` берёт из релиза ссылку,
размер и `digest` установщика, `src/core/app_installer.py` качает и сверяет файл в
`%TEMP%\veblock-update\`, фасад `src/sys/app_install.py` запускает его с UAC и
оставляет PowerShell-наблюдателя, который перезапускает приложение от имени
пользователя (`[Run] runasoriginaluser` у установщика, запущенного через `runas`,
стартовал бы новую версию с правами администратора). Шаги ведёт
`AppController.install_app_update()`: подтверждение, загрузка, отключение, запуск,
`Shell.quit()`. Служба не участвует. Linux не самообновляется: `can_self_update()`
там `False`, GTK показывает «Открыть релиз». Дизайн:
`docs/plans/2026-11-07-windows-self-update-design.md`.
```

**Step 2: Линт и все тесты**

Run:

```bash
uv run ruff check src tests -q && uv run ruff format --check src tests -q
uv run pytest -q
make test-qt
make test-gtk
```

Expected: линт чистый, все прошли. `ruff format` при расхождениях: `uv run ruff format src tests`, затем пересмотри diff.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: самообновление на Windows в CLAUDE.md"
```

**Step 4: Ручная проверка на Windows (вне плана)**

Собрать установщик из ветки, поставить предыдущую версию, поднять версию в ветке, выложить pre-release с ассетом и проверить: тост с кнопкой, «Обновить…», прогресс, UAC (отказ и согласие), выход, тихая установка, перезапуск без повышения прав (в Диспетчере задач столбец «С повышенными правами» — «Нет»).
