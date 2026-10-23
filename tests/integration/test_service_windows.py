"""Служба на настоящей Windows: TUN, маршруты, NRPT и откат.

Запускается в CI после установки службы из собранного каталога:
    TENGA_SERVICE_TESTS=1 python -m pytest tests/integration -m windows
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from src.sys.windows.service_client import ServiceClient
from src.winsvc.state import ServiceError

pytestmark = pytest.mark.windows

# Outbound — SOCKS на закрытый порт loopback: трафик никуда не уходит, но
# валидатор сессии видит настоящий прокси-выход.
CONFIG = {
    "log": {"loglevel": "warning"},
    "inbounds": [
        {
            "tag": "tun-in",
            "protocol": "tun",
            "settings": {"name": "xray0", "MTU": 1500, "gateway": ["198.18.0.1/30"]},
        },
    ],
    "outbounds": [
        {
            "tag": "proxy",
            "protocol": "socks",
            "settings": {"servers": [{"address": "127.0.0.1", "port": 9}]},
        },
        {"tag": "direct", "protocol": "freedom"},
    ],
    "routing": {"rules": []},
}


def ps(script: str):
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script + " | ConvertTo-Json -Compress"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return json.loads(out) if out else None


def routes_on(alias: str) -> set[str]:
    data = ps(
        f"@(Get-NetRoute -InterfaceAlias '{alias}' -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty DestinationPrefix)"
    )
    if isinstance(data, str):
        data = [data]
    return set(data or [])


def nrpt_rules() -> list[str]:
    data = ps(
        "@(Get-DnsClientNrptRule | Where-Object Comment -eq 'tenga-proxy' | "
        "Select-Object -ExpandProperty Name)"
    )
    if isinstance(data, str):
        data = [data]
    return list(data or [])


@pytest.fixture
def client():
    result = ServiceClient()
    yield result
    try:
        result.call("core.stop")
    finally:
        result.close()


def test_tun_session_and_rollback(client):
    client.call("core.start", config=CONFIG)
    client.call("routes.apply", tun_name="xray0", proxy_host="127.0.0.1")
    client.call("dns.apply", tun_name="xray0")
    try:
        assert {"0.0.0.0/1", "128.0.0.0/1"} <= routes_on("xray0")
        assert len(nrpt_rules()) == 1
    finally:
        client.call("core.stop")

    assert not {"0.0.0.0/1", "128.0.0.0/1"} & routes_on("xray0")
    assert nrpt_rules() == []


def test_core_crash_rolls_back(client):
    client.call("core.start", config=CONFIG)
    client.call("routes.apply", tun_name="xray0", proxy_host="127.0.0.1")
    subprocess.run(["taskkill", "/F", "/IM", "xray.exe"], check=False, capture_output=True)

    deadline = time.monotonic() + 5
    while {"0.0.0.0/1", "128.0.0.0/1"} & routes_on("xray0") and time.monotonic() < deadline:
        time.sleep(0.5)

    assert not {"0.0.0.0/1", "128.0.0.0/1"} & routes_on("xray0")
    assert client.call("core.status")["exited"] is True


def test_foreign_config_is_refused(client):
    bad = json.loads(json.dumps(CONFIG))
    bad["inbounds"].append({"tag": "open", "protocol": "socks", "listen": "0.0.0.0", "port": 1080})

    with pytest.raises(ServiceError, match="отклонена"):
        client.call("core.start", config=bad)
