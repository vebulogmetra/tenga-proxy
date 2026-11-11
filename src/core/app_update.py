"""Daily desktop release notifications. Executables are never installed here:
download and verification live in src/core/app_installer.py."""

from __future__ import annotations

import json
import platform
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.core import platform_info

# С 0.30.2 версии для Linux и Windows выходят в своих репозиториях.
LINUX_REPO = "vebulogmetra/veblock-linux"
WINDOWS_REPO = "vebulogmetra/veblock-windows"
_ASSET_NAME = re.compile(r"[A-Za-z0-9._-]+")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
CHECK_INTERVAL_SECONDS = 86400
_lock = threading.Lock()


def release_repo() -> str:
    return WINDOWS_REPO if platform_info.IS_WINDOWS else LINUX_REPO


def releases_url() -> str:
    return f"https://api.github.com/repos/{release_repo()}/releases?per_page=30"


def _release_prefix() -> str:
    return f"/{release_repo()}/releases/tag/"


def _asset_prefix() -> str:
    return f"/{release_repo()}/releases/download/"


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


def safe_release_url(url: str) -> bool:
    prefix = _release_prefix()
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.netloc == "github.com"
            and not parts.query
            and not parts.fragment
            and parts.path.startswith(prefix)
            and len(parts.path) > len(prefix)
            and _version(parts.path[len(prefix) :]) is not None
        )
    except ValueError:
        return False


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
        and parts.path == f"{_asset_prefix()}{tag}/{name}"
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


def _version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)(?:\.?(\d+))?)?", value)
    if not match:
        return None
    major, minor, patch, stage, number = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage],
        int(number or 0),
    )


def _asset_matches(name: str, aliases: tuple[str, ...]) -> bool:
    """Сборка для этой системы: установщик на Windows, deb-пакет на Linux."""
    name = name.lower()
    if platform_info.IS_WINDOWS:
        return (
            name.endswith("-setup.exe")
            and "windows" in name
            and ("x64" in name or any(alias in name for alias in aliases))
        )
    return name.endswith(".deb") and any(alias in name for alias in aliases)


def select_release(payload, current, *, include_prerelease=False, architecture=None):
    installed = _version(current)
    if installed is None:
        return None
    # platform.machine() на Windows — «AMD64».
    arch = (architecture or platform.machine()).lower()
    aliases = (
        ("x86_64", "amd64")
        if arch in ("x86_64", "amd64")
        else ("aarch64", "arm64")
        if arch in ("aarch64", "arm64")
        else (arch,)
    )
    candidates = []
    for release in payload if isinstance(payload, list) else []:
        if (
            not isinstance(release, dict)
            or release.get("draft")
            or (release.get("prerelease") and not include_prerelease)
        ):
            continue
        version = str(release.get("tag_name", ""))
        parsed = _version(version)
        url = str(release.get("html_url", ""))
        if parsed is None or parsed <= installed or not safe_release_url(url):
            continue
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            assets = []
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
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def fetch_app_releases(proxy_url=None):
    from src.sub.updater import SubscriptionUpdater

    # No device headers, even if enabled for subscriptions in the main config.
    return json.loads(SubscriptionUpdater(proxy_url=proxy_url).fetch(releases_url()))


def check_app_update(config, current, *, fetch=fetch_app_releases, now=None, force=False):
    now = int(time.time()) if now is None else now
    with _lock:
        if not force and (
            not config.app_update_enabled
            or (
                config.app_update_last_attempt
                and now - config.app_update_last_attempt < CHECK_INTERVAL_SECONDS
            )
        ):
            return None
        config.app_update_last_attempt = now
        payload = fetch()
        if not isinstance(payload, list):
            raise ValueError("Некорректный ответ сервиса релизов")
        selected = select_release(payload, current, include_prerelease=config.app_update_prerelease)
        config.app_update_last_success = now
        config.app_update_target = selected.version if selected else ""
        config.app_update_url = selected.url if selected else ""
        config.app_update_has_asset = bool(selected and selected.has_asset)
        config.app_update_asset_url = selected.asset_url if selected else ""
        config.app_update_asset_size = selected.asset_size if selected else 0
        config.app_update_asset_digest = selected.asset_digest if selected else ""
        return selected
