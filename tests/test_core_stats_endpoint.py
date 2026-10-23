"""Stats access: a per-run private Unix socket on Linux, loopback TCP on Windows."""

import sys
from pathlib import Path

import pytest

from src.core.xray_manager import XrayManager


@pytest.mark.skipif(sys.platform == "win32", reason="unix-сокет статистики — только Linux")
def test_stats_socket_is_private_and_input_config_is_not_modified(monkeypatch):
    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    manager = XrayManager(binary_path="/nonexistent")
    original = {"inbounds": [], "outbounds": [], "routing": {"rules": []}}
    config = manager._inject_stats_api(original)
    inbound = next(item for item in config["inbounds"] if item["tag"] == "api")
    assert "port" not in inbound
    assert Path(inbound["listen"]).is_absolute()
    assert Path(inbound["listen"]).parent.stat().st_mode & 0o777 == 0o700
    assert original["inbounds"] == []
    assert original["routing"]["rules"] == []
    assert config["api"]["services"] == ["StatsService"]
    first = inbound["listen"]
    manager._cleanup()
    assert not Path(first).parent.exists()
    new_config = manager._inject_stats_api({})
    assert new_config["inbounds"][0]["listen"] != first
    manager._cleanup()


def test_real_core_answers_stats_query(tmp_path):
    import json
    import subprocess
    import time

    from src.core.config import XRAY_BINARY_NAME, find_xray_binary

    bundled = Path(__file__).resolve().parents[1] / "core" / "bin" / XRAY_BINARY_NAME
    binary = str(bundled) if bundled.is_file() else find_xray_binary()
    if not binary:
        pytest.skip("xray is unavailable")
    manager = XrayManager(binary_path=binary)
    config = manager._inject_stats_api({"outbounds": [{"protocol": "freedom", "tag": "proxy"}]})
    source = tmp_path / "config.json"
    source.write_text(json.dumps(config))
    process = subprocess.Popen(
        [binary, "run", "-c", str(source)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        deadline = time.monotonic() + 5
        while True:
            answer = subprocess.run(
                [binary, "api", "statsquery", f"--server={manager._stats_api_addr}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if answer.returncode == 0 or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        assert answer.returncode == 0, answer.stderr
        assert isinstance(json.loads(answer.stdout), dict)
        if sys.platform != "win32":
            assert all("port" not in inbound for inbound in config["inbounds"])
    finally:
        process.terminate()
        process.communicate(timeout=3)
        manager._cleanup()


def test_windows_stats_listen_on_loopback_port(monkeypatch):
    from src.core import platform_info, stats_endpoint

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    endpoint = stats_endpoint.StatsEndpoint()

    settings = endpoint.listen_settings()

    assert settings["listen"] == "127.0.0.1"
    assert 0 < settings["port"] < 65536
    assert endpoint.address == f"127.0.0.1:{settings['port']}"
    endpoint.close()
    assert endpoint._port is None
