from __future__ import annotations

import json
import subprocess

from src.core.xray_manager import TrafficStats, XrayManager


def _answering(monkeypatch, stdout: str, returncode: int = 0) -> None:
    """Make the stats call return this text instead of running the core."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, returncode, stdout=stdout, stderr=""
        ),
    )


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


_STATS_ANSWER = """
{
    "stat": [
        {"name": "outbound>>>proxy>>>traffic>>>uplink", "value": 1024},
        {"name": "outbound>>>proxy>>>traffic>>>downlink", "value": 2048},
        {"name": "outbound>>>api>>>traffic>>>uplink"}
    ]
}
"""


def test_get_traffic_reads_the_counters(monkeypatch):
    """Цифры берутся из ответа ядра, а не выдумываются нулями."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, _STATS_ANSWER)

    stats = manager.get_traffic()

    assert stats.upload == 1024
    assert stats.download == 2048


def test_get_traffic_asks_the_core_for_stats(monkeypatch):
    """Опрос идёт вызовом statsquery у того же бинарника."""
    manager = _make_manager(monkeypatch)
    seen: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=_STATS_ANSWER, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    manager.get_traffic()

    assert seen, "статистику обязаны были спросить у ядра"
    command = seen[0]
    assert command[0] == "/nonexistent"
    assert command[1:3] == ["api", "statsquery"]
    assert any(part.startswith("--server=") for part in command)


def test_get_traffic_counts_a_missing_value_as_zero(monkeypatch):
    """Обнулённый счётчик приходит без ключа value, а не с нулём в нём."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, '{"stat": [{"name": "outbound>>>proxy>>>traffic>>>uplink"}]}')

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_dead_core(monkeypatch):
    """Опрос идёт по таймеру: упасть при остановленном ядре он не вправе."""
    manager = _make_manager(monkeypatch)

    def explode(*_args, **_kwargs):
        raise OSError("нет такого файла")

    monkeypatch.setattr(subprocess, "run", explode)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_timeout(monkeypatch):
    """Зависший вызов гасится таймаутом и не роняет опрос."""
    manager = _make_manager(monkeypatch)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="xray", timeout=5)

    monkeypatch.setattr(subprocess, "run", timeout)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_broken_output(monkeypatch):
    """Ответ не по формату — это нули, а не исключение."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, "не json")

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_failing_call(monkeypatch):
    """Ненулевой код возврата означает, что спрашивать нечего."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, "", returncode=1)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_sums_the_proxy_outbounds(monkeypatch):
    """Тег outbound — имя профиля; служебные каналы в счёт не идут."""
    manager = _make_manager(monkeypatch)
    profile = "🇵🇱Польша | XHTTP VPN#6"
    _answering(
        monkeypatch,
        json.dumps(
            {
                "stat": [
                    {"name": f"outbound>>>{profile}>>>traffic>>>uplink", "value": 500},
                    {"name": f"outbound>>>{profile}>>>traffic>>>downlink", "value": 900},
                    {"name": "outbound>>>direct>>>traffic>>>uplink", "value": 111},
                    {"name": "outbound>>>vpn>>>traffic>>>downlink", "value": 222},
                    {"name": "outbound>>>api>>>traffic>>>uplink", "value": 333},
                    {"name": "outbound>>>main-dns>>>traffic>>>downlink", "value": 444},
                    {"name": "outbound>>>local-dns>>>traffic>>>uplink", "value": 555},
                    {"name": "outbound>>>vpn-dns>>>traffic>>>downlink", "value": 666},
                    {"name": "inbound>>>tun-in>>>traffic>>>uplink", "value": 777},
                ]
            }
        ),
    )

    assert manager.get_traffic() == TrafficStats(upload=500, download=900)


def test_get_traffic_still_counts_an_unnamed_profile(monkeypatch):
    """У безымянного профиля тегом остаётся proxy: он тоже трафик прокси."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, _STATS_ANSWER)

    assert manager.get_traffic() == TrafficStats(upload=1024, download=2048)


def test_get_traffic_ignores_a_malformed_counter_name(monkeypatch):
    """Имя не из четырёх частей пропускается, а не роняет разбор."""
    manager = _make_manager(monkeypatch)
    _answering(
        monkeypatch,
        json.dumps(
            {
                "stat": [
                    {"name": "outbound>>>node>>>uplink", "value": 10},
                    {"name": "странное имя", "value": 20},
                    {"name": "outbound>>>node>>>traffic>>>uplink", "value": 30},
                ]
            }
        ),
    )

    assert manager.get_traffic() == TrafficStats(upload=30, download=0)
