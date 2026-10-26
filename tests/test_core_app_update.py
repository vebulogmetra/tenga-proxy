import pytest

from src.core.app_update import check_app_update, safe_release_url, select_release
from src.db.data_store import DataStore

RELEASE = {
    "tag_name": "v0.17.0",
    "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.17.0",
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


def test_windows_release_needs_setup_exe(monkeypatch):
    from src.core import app_update, platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    payload = [
        {
            "tag_name": "v0.18.0",
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
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
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.19.0",
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
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
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
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
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
            "html_url": "https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.18.0",
            "assets": [{"name": "tenga-proxy_0.18.0_arm64.deb"}],
        }
    ]

    assert app_update.select_release(payload, "0.17.0", architecture="aarch64").has_asset is True
