from __future__ import annotations

from src.core.xray_manager import XrayManager


def _make_manager(monkeypatch) -> XrayManager:
    """Manager that never touches the real binary.

    Конструктор спрашивает у ядра версию, запуская процесс: тестам это не
    нужно и в среде без бинарника только мешает.
    """
    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    return XrayManager(binary_path="/nonexistent")


def test_inject_stats_api_enables_the_outbound_counters(monkeypatch):
    """Без policy ядро не считает трафик, сколько ни включай stats."""
    manager = _make_manager(monkeypatch)
    config = manager._inject_stats_api({"inbounds": [], "outbounds": []})

    system = config["policy"]["system"]
    assert system["statsOutboundUplink"] is True
    assert system["statsOutboundDownlink"] is True


def test_inject_stats_api_keeps_an_existing_policy(monkeypatch):
    """Своя policy пользователя не затирается, счётчики к ней добавляются."""
    manager = _make_manager(monkeypatch)
    config = manager._inject_stats_api({"policy": {"levels": {"0": {"handshake": 4}}}})

    assert config["policy"]["levels"] == {"0": {"handshake": 4}}
    assert config["policy"]["system"]["statsOutboundUplink"] is True


def test_inject_stats_api_leaves_the_original_config_alone(monkeypatch):
    """Аргумент не правится на месте: копия словаря поверхностная."""
    manager = _make_manager(monkeypatch)
    original = {"policy": {"system": {"statsInboundUplink": True}}}

    manager._inject_stats_api(original)

    assert original["policy"]["system"] == {"statsInboundUplink": True}
