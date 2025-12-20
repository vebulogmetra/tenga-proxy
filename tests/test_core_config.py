import importlib
import sys

import pytest


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in ["TENGA_CONFIG_DIR", "XDG_CONFIG_HOME", "APPIMAGE"]:
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


def test_get_config_dir_appimage_xdg(clean_env, monkeypatch, tmp_path):
    xdg_config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setenv("APPIMAGE", "/tmp/fake_appimage")

    config = _reload_config_module()

    expected = xdg_config_home / "tenga-proxy"
    assert expected == config.CORE_DIR
    assert expected.exists()


def test_get_config_dir_development_mode(clean_env, monkeypatch):
    if hasattr(sys, "frozen"):
        monkeypatch.delattr(sys, "frozen", raising=False)
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    monkeypatch.delenv("APPIMAGE", raising=False)

    import src.core.config as config

    config = importlib.reload(config)

    # PROJECT_ROOT/ core
    expected_core = config.Path(__file__).resolve().parent.parent / "core"
    assert expected_core == config.CORE_DIR


def test_log_dir_created(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPIMAGE", "/tmp/fake_appimage")

    config = _reload_config_module()

    assert config.LOG_DIR.exists()
    assert str(config.GUI_LOG_FILE).startswith(str(config.LOG_DIR))
    assert str(config.CLI_LOG_FILE).startswith(str(config.LOG_DIR))
    assert str(config.XRAY_LOG_FILE).startswith(str(config.LOG_DIR))


def test_get_lock_file_default_and_custom(tmp_path):
    import src.core.config as config

    default_lock = config.get_lock_file()
    assert default_lock.parent == config.CORE_DIR
    assert default_lock.name == "tenga-proxy.lock"

    custom_dir = tmp_path / "config"
    custom_lock = config.get_lock_file(custom_dir)
    assert custom_lock.parent == custom_dir
    assert custom_lock.name == "tenga-proxy.lock"
