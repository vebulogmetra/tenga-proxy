"""Daily desktop release notifications. Executables are never installed here."""

from __future__ import annotations

import json
import platform
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.core import platform_info

RELEASES_URL = "https://api.github.com/repos/vebulogmetra/tenga-proxy/releases?per_page=30"
RELEASE_PREFIX = "/vebulogmetra/tenga-proxy/releases/tag/"
CHECK_INTERVAL_SECONDS = 86400
_lock = threading.Lock()


@dataclass(frozen=True)
class AppRelease:
    version: str
    url: str
    has_asset: bool


def safe_release_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.netloc == "github.com"
            and not parts.query
            and not parts.fragment
            and parts.path.startswith(RELEASE_PREFIX)
            and len(parts.path) > len(RELEASE_PREFIX)
            and _version(parts.path[len(RELEASE_PREFIX) :]) is not None
        )
    except ValueError:
        return False


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
        has_asset = any(
            isinstance(asset, dict) and _asset_matches(str(asset.get("name", "")), aliases)
            for asset in assets
        )
        candidates.append((parsed, AppRelease(version, url, has_asset)))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def fetch_app_releases(proxy_url=None):
    from src.sub.updater import SubscriptionUpdater

    # No device headers, even if enabled for subscriptions in the main config.
    return json.loads(SubscriptionUpdater(proxy_url=proxy_url).fetch(RELEASES_URL))


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
        return selected
