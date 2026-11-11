import pytest

from src.core.app_update import check_app_update, safe_release_url, select_release
from src.db.data_store import DataStore

RELEASE = {
    "tag_name": "v0.17.0",
    "html_url": "https://github.com/vebulogmetra/veblock-linux/releases/tag/v0.17.0",
    "assets": [{"name": "tenga-proxy_0.17.0_amd64.deb"}],
}


def test_release_selection_handles_drafts_prereleases_and_architecture(monkeypatch):
    from src.core import platform_info

    # Ассеты здесь — deb-пакеты: на Windows ищется установщик.
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)
    assert select_release([dict(RELEASE, draft=True)], "0.16.2") is None
    assert select_release([dict(RELEASE, prerelease=True)], "0.16.2") is None
    assert select_release([RELEASE], "0.16.2", architecture="x86_64").has_asset
    assert not select_release([RELEASE], "0.16.2", architecture="aarch64").has_asset
    assert select_release([RELEASE], "0.17.0") is None
    assert select_release([RELEASE], "0.17.0.dev1") is None


def test_failed_check_is_rate_limited_separately_from_success():
    config = DataStore()

    def fail():
        raise OSError("offline")

    with pytest.raises(OSError, match="offline"):
        check_app_update(config, "0.16.2", fetch=fail, now=200000)
    assert config.app_update_last_attempt == 200000
    assert config.app_update_last_success == 0
    assert check_app_update(config, "0.16.2", fetch=fail, now=200001) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/vebulogmetra/tenga-proxy/releases/tag/1",
        "https://evil.example/releases/tag/1",
        "https://github.com/other/repo/releases/tag/1",
        "https://github.com/vebulogmetra/tenga-proxy/releases/tag/1?token=secret",
    ],
)
def test_untrusted_release_link_is_rejected(url):
    assert not safe_release_url(url)


@pytest.mark.parametrize(
    ("windows", "repo", "other"),
    [(False, "veblock-linux", "veblock-windows"), (True, "veblock-windows", "veblock-linux")],
)
def test_releases_come_from_the_platform_repo(monkeypatch, windows, repo, other):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
    tag = "https://github.com/vebulogmetra/{}/releases/tag/v0.31.0"

    assert app_update.releases_url().startswith(
        f"https://api.github.com/repos/vebulogmetra/{repo}/"
    )
    assert safe_release_url(tag.format(repo))
    assert not safe_release_url(tag.format(other))
    assert not safe_release_url(tag.format("tenga-proxy"))


def test_windows_release_needs_setup_exe(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/veblock-windows/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy-0.18.0-windows-x64-setup.exe"}],
        }
    ]

    release = app_update.select_release(payload, "0.17.0", architecture="AMD64")

    assert release.has_asset is True


def test_windows_release_finds_the_renamed_setup_exe(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.19.0",
            "html_url": "https://github.com/vebulogmetra/veblock-windows/releases/tag/v0.19.0",
            "assets": [{"name": "veblock-0.19.0-windows-x64-setup.exe"}],
        }
    ]

    release = app_update.select_release(payload, "0.18.0", architecture="AMD64")

    assert release.has_asset is True


def test_windows_ignores_deb(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/veblock-windows/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy_0.18.0_amd64.deb"}],
        }
    ]

    assert app_update.select_release(payload, "0.17.0", architecture="AMD64").has_asset is False


def test_linux_ignores_appimage(monkeypatch):
    """AppImage больше не выпускается: старый ассет не считается сборкой для Linux."""
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/veblock-linux/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy-0.18.0-x86_64.AppImage"}],
        }
    ]

    assert app_update.select_release(payload, "0.17.0", architecture="x86_64").has_asset is False


def test_linux_deb_matches_arm64(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/veblock-linux/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy_0.18.0_arm64.deb"}],
        }
    ]

    assert app_update.select_release(payload, "0.17.0", architecture="aarch64").has_asset is True


WINDOWS_ASSET = {
    "name": "veblock-0.19.0-windows-x64-setup.exe",
    "browser_download_url": (
        "https://github.com/vebulogmetra/veblock-windows/releases/download/v0.19.0/"
        "veblock-0.19.0-windows-x64-setup.exe"
    ),
    "size": 70_000_000,
    "digest": "sha256:" + "ab" * 32,
}
WINDOWS_RELEASE = {
    "tag_name": "v0.19.0",
    "html_url": "https://github.com/vebulogmetra/veblock-windows/releases/tag/v0.19.0",
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
            "browser_download_url": "https://github.com/vebulogmetra/veblock-windows/releases/"
            "download/v0.18.0/veblock-0.19.0-windows-x64-setup.exe"
        },
        {
            "browser_download_url": "https://github.com/vebulogmetra/veblock-windows/releases/"
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
