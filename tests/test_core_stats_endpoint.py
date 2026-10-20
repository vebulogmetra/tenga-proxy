"""Stats access must use a per-run private Unix socket, never an open TCP port."""

from pathlib import Path

from src.core.xray_manager import XrayManager


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


def test_real_core_can_query_private_socket_without_tcp(tmp_path):
    import json
    import subprocess
    import time

    import pytest

    from src.core.config import find_xray_binary

    bundled = Path(__file__).resolve().parents[1] / "core" / "bin" / "xray"
    binary = str(bundled) if bundled.is_file() else find_xray_binary()
    if not binary:
        pytest.skip("xray is unavailable")
    manager = XrayManager(binary_path=binary)
    config = manager._inject_stats_api({"outbounds": [{"protocol": "freedom", "tag": "proxy"}]})
    path = Path(config["inbounds"][0]["listen"])
    source = tmp_path / "config.json"
    source.write_text(json.dumps(config))
    process = subprocess.Popen(
        [binary, "run", "-c", str(source)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        deadline = time.monotonic() + 3
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        answer = subprocess.run(
            [binary, "api", "statsquery", f"--server=unix://{path}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert answer.returncode == 0, answer.stderr
        assert isinstance(json.loads(answer.stdout), dict)
        assert all("port" not in inbound for inbound in config["inbounds"])
    finally:
        process.terminate()
        process.communicate(timeout=3)
        manager._cleanup()
    assert not path.parent.exists()
