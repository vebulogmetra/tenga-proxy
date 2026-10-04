"""Служебный inbound проверки соединения в рабочем конфиге."""

from __future__ import annotations

import http.server
import shutil
import threading
from pathlib import Path

import pytest
import requests

from src.core.batch_probe import BatchCore, core_accepts, reserve_ports
from src.core.config_builder import build_session_config
from src.core.context import init_context
from src.core.health_probe import (
    HEALTH_INBOUND_TAG,
    attach_health_inbound,
    new_health_endpoint,
    redact_health_credentials,
)
from src.core.http_probe import ProbeCredentials, ProbeEndpoint, measure_latency
from src.db.config import ProxyMode
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

ENDPOINT = ProbeEndpoint(port=41500, credentials=ProbeCredentials("health", "secret"))


def session_config(proxy: dict | None = None) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "tun-in", "protocol": "tun"}],
        "outbounds": [
            proxy or {"protocol": "vless", "tag": "proxy"},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "domainStrategy": "IPOnDemand",
            "rules": [{"type": "field", "domain": ["example.com"], "outboundTag": "direct"}],
        },
    }


def test_health_endpoint_gets_a_free_loopback_port_and_fresh_credentials():
    first = new_health_endpoint()
    second = new_health_endpoint()

    assert first.host == "127.0.0.1"
    assert first.port > 0
    assert first.credentials != second.credentials


def test_health_inbound_is_an_authenticated_http_proxy_on_loopback():
    config = attach_health_inbound(session_config(), ENDPOINT)

    inbound = config["inbounds"][-1]
    assert inbound == {
        "tag": HEALTH_INBOUND_TAG,
        "listen": "127.0.0.1",
        "port": 41500,
        "protocol": "http",
        "settings": {"accounts": [{"user": "health", "pass": "secret"}]},
    }
    assert config["inbounds"][0]["tag"] == "tun-in"


def test_health_rule_goes_first_and_points_at_the_profile_outbound():
    config = attach_health_inbound(
        session_config({"protocol": "trojan", "tag": "my-proxy"}), ENDPOINT
    )

    rules = config["routing"]["rules"]
    assert rules[0] == {
        "type": "field",
        "inboundTag": [HEALTH_INBOUND_TAG],
        "outboundTag": "my-proxy",
    }
    # Пользовательские правила остаются, но идут после.
    assert rules[1]["domain"] == ["example.com"]


def test_health_inbound_tolerates_a_config_without_routing():
    config = attach_health_inbound({"outbounds": [{"protocol": "vless", "tag": "proxy"}]}, ENDPOINT)

    assert config["inbounds"][0]["tag"] == HEALTH_INBOUND_TAG
    assert config["routing"]["rules"][0]["outboundTag"] == "proxy"


def test_redacted_copy_hides_credentials_and_leaves_the_config_intact():
    config = attach_health_inbound(session_config(), ENDPOINT)

    redacted = redact_health_credentials(config)

    assert redacted["inbounds"][-1]["settings"]["accounts"] == [{"user": "***", "pass": "***"}]
    assert redacted["inbounds"][-1]["port"] == 41500
    assert config["inbounds"][-1]["settings"]["accounts"] == [{"user": "health", "pass": "secret"}]


# --- настоящее ядро: проверка не должна обходить прокси по direct-правилам ---


class _Site(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def local_site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/generate_204"
    server.shutdown()
    server.server_close()


def running_config(proxy: dict, plain_port: int, health: ProbeEndpoint) -> dict:
    """Рабочий конфиг в миниатюре: сайт проверки попадает под direct-правило."""
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "http-plain", "listen": "127.0.0.1", "port": plain_port, "protocol": "http"}
        ],
        "outbounds": [proxy, {"protocol": "freedom", "tag": "direct"}],
        "routing": {
            "rules": [{"type": "field", "ip": ["127.0.0.0/8"], "outboundTag": "direct"}],
        },
    }
    return attach_health_inbound(config, health)


@needs_xray
def test_check_through_an_ordinary_inbound_misses_a_dead_proxy(local_site):
    """Зачем нужен отдельный inbound: обычный путь подчиняется правилам пользователя.

    Прокси мёртв (blackhole), но адрес проверки попадает под direct-правило —
    запрос через обычный inbound проходит, и проверка ошибочно говорит «всё хорошо».
    """
    plain_port, health_port = reserve_ports(2)
    health = ProbeEndpoint(health_port, ProbeCredentials.generate())
    config = running_config({"protocol": "blackhole", "tag": "proxy"}, plain_port, health)

    with BatchCore(str(XRAY), config) as core:
        assert core.wait_ready([plain_port, health_port])
        with requests.Session() as session:
            session.trust_env = False
            plain = session.head(
                local_site, proxies={"http": f"http://127.0.0.1:{plain_port}"}, timeout=5
            )
        through_health = measure_latency(health, local_site, probes=1)

    assert plain.status_code == 204
    assert through_health == -1


@needs_xray
def test_check_through_the_health_inbound_passes_when_the_proxy_works(local_site):
    plain_port, health_port = reserve_ports(2)
    health = ProbeEndpoint(health_port, ProbeCredentials.generate())
    config = running_config({"protocol": "freedom", "tag": "proxy"}, plain_port, health)

    with BatchCore(str(XRAY), config) as core:
        assert core.wait_ready([plain_port, health_port])
        through_health = measure_latency(health, local_site, probes=1)

    assert through_health >= 0


@needs_xray
def test_core_accepts_a_real_session_config_with_the_health_inbound(tmp_path):
    """Конфиг из рабочего билдера с добавленным inbound'ом ядро принимает."""
    context = init_context(config_dir=tmp_path)
    # Только системный прокси: `xray -test` на TUN-конфиге трогает интерфейсы.
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
    bean = parse_link(
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        "?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
    )
    config = build_session_config(context, ProfileEntry(id=1, group_id=0, bean=bean))
    assert config is not None

    attach_health_inbound(config, new_health_endpoint())

    assert all(inbound["protocol"] != "tun" for inbound in config["inbounds"])
    assert core_accepts(str(XRAY), config) is True
