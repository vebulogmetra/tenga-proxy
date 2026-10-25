import importlib
import sys

import pytest


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in ["TENGA_CONFIG_DIR", "XDG_CONFIG_HOME"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _reload_config_module():
    import src.core.config as config

    return importlib.reload(config)


def test_get_config_dir_uses_env_var(clean_env, monkeypatch, tmp_path):
    custom_dir = tmp_path / "custom_config"
    monkeypatch.setenv("TENGA_CONFIG_DIR", str(custom_dir))

    config = _reload_config_module()

    assert custom_dir == config.CORE_DIR
    assert config.CORE_DIR.exists()


def test_get_config_dir_development_mode(clean_env, monkeypatch):
    if hasattr(sys, "frozen"):
        monkeypatch.delattr(sys, "frozen", raising=False)
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    import src.core.config as config

    config = importlib.reload(config)

    # PROJECT_ROOT/ core
    expected_core = config.Path(__file__).resolve().parent.parent / "core"
    assert expected_core == config.CORE_DIR


def test_log_dir_created(clean_env, tmp_path, monkeypatch):
    # Каталог, заданный снаружи, забирает и логи.
    monkeypatch.setenv("TENGA_CONFIG_DIR", str(tmp_path / "xdg" / "tenga-proxy"))

    config = _reload_config_module()

    assert config.LOG_DIR.exists()
    assert str(config.GUI_LOG_FILE).startswith(str(config.LOG_DIR))
    assert str(config.CLI_LOG_FILE).startswith(str(config.LOG_DIR))
    assert str(config.XRAY_LOG_FILE).startswith(str(config.LOG_DIR))
    assert tmp_path / "xdg" / "tenga-proxy" / "logs" == config.LOG_DIR


def test_get_lock_file_default_and_custom(tmp_path):
    import src.core.config as config

    default_lock = config.get_lock_file()
    assert default_lock.parent == config.CORE_DIR
    assert default_lock.name == "tenga-proxy.lock"

    custom_dir = tmp_path / "config"
    custom_lock = config.get_lock_file(custom_dir)
    assert custom_lock.parent == custom_dir
    assert custom_lock.name == "tenga-proxy.lock"


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

    assert as_windows / "Roaming" / "tenga-proxy" == config.CORE_DIR
    assert as_windows / "Local" / "tenga-proxy" / "logs" == config.LOG_DIR


def test_windows_binary_name_has_exe(as_windows):
    config = _reload_config_module()

    assert config.XRAY_BINARY_NAME == "xray.exe"


def test_windows_env_var_still_wins(as_windows, monkeypatch):
    custom = as_windows / "custom"
    monkeypatch.setenv("TENGA_CONFIG_DIR", str(custom))

    config = _reload_config_module()

    assert custom == config.CORE_DIR


def _fake_xray(directory):
    directory.mkdir(parents=True)
    binary = directory / "xray"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


@pytest.mark.skipif(sys.platform == "win32", reason="сценарий оболочки вместо xray")
def test_xray_from_the_package_wins_over_the_user_copy(monkeypatch, tmp_path):
    """Ядро из пакета получило cap_net_admin в postinst; копия, которую
    ставила AppImage в ~/.config/tenga-proxy/bin, устарела и не должна его
    перекрывать."""
    import src.core.config as config

    bundled = _fake_xray(tmp_path / "pkg" / "core" / "bin")
    _fake_xray(tmp_path / "user" / "bin")
    monkeypatch.setattr(config, "BUNDLE_DIR", tmp_path / "pkg")
    monkeypatch.setattr(config, "CORE_BIN_DIR", tmp_path / "user" / "bin")

    assert config.find_xray_binary() == str(bundled)


@pytest.mark.skipif(sys.platform == "win32", reason="сценарий оболочки вместо xray")
def test_user_xray_is_used_without_a_bundled_one(monkeypatch, tmp_path):
    import src.core.config as config

    user = _fake_xray(tmp_path / "user" / "bin")
    monkeypatch.setattr(config, "BUNDLE_DIR", tmp_path / "pkg")
    monkeypatch.setattr(config, "CORE_BIN_DIR", tmp_path / "user" / "bin")

    assert config.find_xray_binary() == str(user)


def test_package_install_uses_xdg_dirs(clean_env, monkeypatch, tmp_path):
    """Из /usr/lib/tenga-proxy писать нельзя: конфигурация и логи — в ~/.config."""
    import src.core.config as config

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(config, "_get_bundle_dir", lambda: config.PACKAGE_DIR)

    assert config._get_config_dir() == tmp_path / "xdg" / "tenga-proxy"
    assert config._get_log_dir() == tmp_path / "xdg" / "tenga-proxy" / "logs"


def test_is_packaged_only_under_the_package_dir(monkeypatch):
    import src.core.config as config

    monkeypatch.setattr(config, "BUNDLE_DIR", config.PACKAGE_DIR)
    assert config.is_packaged() is True

    monkeypatch.setattr(config, "BUNDLE_DIR", config.PACKAGE_DIR.parent / "src-checkout")
    assert config.is_packaged() is False
