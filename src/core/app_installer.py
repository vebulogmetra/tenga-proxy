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
