from typing import List, Tuple

from src.sys import proxy


class _FakeResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_is_kde_true_and_false(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_DESKTOP", "KDE")
    assert proxy._is_kde() is True

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "plasma")
    assert proxy._is_kde() is True

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "gnome")
    assert proxy._is_kde() is False


def test_get_config_path_uses_xdg_config_home(monkeypatch, tmp_path):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert proxy._get_config_path() == xdg


def test_get_config_path_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert proxy._get_config_path() == tmp_path / ".config"


def test_set_system_proxy_no_ports_returns_false(capsys):
    assert proxy.set_system_proxy(http_port=0, socks_port=0) is False
    captured = capsys.readouterr()
    assert "Nothing to set" in captured.out


def test_set_system_proxy_gnome_http_and_socks(monkeypatch):
    recorded: List[Tuple[str, List[str]]] = []

    def fake_exec(program: str, args: List[str]) -> bool:
        recorded.append((program, args))
        return True

    # GNOME: _is_kde -> False
    monkeypatch.setenv("XDG_SESSION_DESKTOP", "gnome")
    monkeypatch.setattr(proxy, "_execute_command", fake_exec)

    ok = proxy.set_system_proxy(http_port=8080, socks_port=1080, address="10.0.0.1")
    assert ok is True

    programs = [p for p, _ in recorded]
    assert "gsettings" in programs
    assert any(
        args[:3] == ["set", "org.gnome.system.proxy.http", "host"]
        for p, args in recorded
        if p == "gsettings"
    )


def test_set_system_proxy_kde_http_only(monkeypatch, tmp_path):
    recorded: List[Tuple[str, List[str]]] = []

    def fake_exec(program: str, args: List[str]) -> bool:
        recorded.append((program, args))
        return True

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(proxy, "_execute_command", fake_exec)

    ok = proxy.set_system_proxy(http_port=3128, socks_port=0, address="127.0.0.1")
    assert ok is True

    programs = [p for p, _ in recorded]
    assert "kwriteconfig5" in programs
    assert "dbus-send" in programs


def test_clear_system_proxy_gnome(monkeypatch):
    recorded: List[Tuple[str, List[str]]] = []

    def fake_exec(program: str, args: List[str]) -> bool:
        recorded.append((program, args))
        return True

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "gnome")
    monkeypatch.setattr(proxy, "_execute_command", fake_exec)

    ok = proxy.clear_system_proxy()
    assert ok is True

    assert recorded[0][0] == "gsettings"
    assert recorded[0][1] == ["set", "org.gnome.system.proxy", "mode", "none"]


def test_clear_system_proxy_kde(monkeypatch, tmp_path):
    recorded: List[Tuple[str, List[str]]] = []

    def fake_exec(program: str, args: List[str]) -> bool:
        recorded.append((program, args))
        return True

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(proxy, "_execute_command", fake_exec)

    ok = proxy.clear_system_proxy()
    assert ok is True

    programs = [p for p, _ in recorded]
    assert "kwriteconfig5" in programs
    assert "dbus-send" in programs
