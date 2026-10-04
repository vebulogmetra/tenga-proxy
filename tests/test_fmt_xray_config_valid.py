"""Проверка сгенерированных конфигов настоящим бинарником xray.

Юнит-тесты подтверждают только внутреннюю согласованность Python-кода: схему
конфига знает лишь ядро. Эти тесты ловят расхождение со схемой форка — например,
`network: "udp"` или настройки в виде `servers[]`, которые ядро молча не принимает.
"""

import base64
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

from src.fmt import parse_link

XRAY = Path("core/bin/xray")

pytestmark = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

SS_2022_KEY = quote(base64.b64encode(bytes([0xFB, 0xEF, 0xFF] * 10 + [1, 2])).decode(), safe="")
FM = quote('{"salamander":{"password":"secret"}}')
EXTRA = quote('{"scMaxEachPostBytes":1000000,"xmux":{"maxConcurrency":"16-32"},"seqKey":"abc"}')

LINKS = {
    "hysteria2": (
        "hysteria2://pass123@127.0.0.1:8443"
        f"?sni=cdn.example.com&alpn=h3&obfs=salamander&obfs-password=obfspass&fm={FM}#H2"
    ),
    "hysteria2_plain": "hysteria2://pass123@127.0.0.1:8443#H2",
    # obfs разворачивается в udp-маску finalmask — ядро проверяет тип маски.
    "hysteria2_obfs": (
        "hysteria2://pass123@127.0.0.1:8443?obfs=salamander&obfs-password=obfspass#H2O"
    ),
    # udphop и brutal: нужны ядру новее 26.3.27 (там «unknown config id: udphop»).
    "hysteria2_hop": (
        "hysteria2://pass123@127.0.0.1:8443,20000-50000/?sni=cdn.example.com"
        "&hop-interval=20-40&obfs=salamander&obfs-password=obfspass&upmbps=50&downmbps=100#HH"
    ),
    "hysteria2_mport": "hysteria2://pass123@127.0.0.1:8443?mport=20000-50000&upmbps=50#HM",
    "xhttp": (
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        f"?type=xhttp&security=tls&sni=a.example.com&mode=stream-one"
        f"&xPaddingBytes=100-1000&extra={EXTRA}#X"
    ),
    # allowInsecure ядро удалило: с ним конфиг не грузится вовсе.
    "vless_allow_insecure": (
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        "?type=tcp&security=tls&sni=a.example.com&allowInsecure=1#VI"
    ),
    "trojan_allow_insecure": (
        "trojan://pass123@127.0.0.1:443?type=ws&path=%2Fws&sni=a.example.com&allowInsecure=1#TI"
    ),
    "hysteria2_insecure": "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com&insecure=1#HI",
    # spiderX без ведущего слэша ядро отвергает («invalid "spiderX"»).
    "reality_bad_spider_x": (
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        "?type=tcp&security=reality&sni=a.example.com"
        "&pbk=7xhH4b_VkliBxGULljcyPOH-bYUA2dl-XAdZAsfhk04&sid=ab&spx=spider&fp=chrome#RS"
    ),
    "shadowsocks_aead": "ss://YWVzLTI1Ni1nY206cGFzcw@127.0.0.1:8388#SS",
    "shadowsocks_2022": f"ss://2022-blake3-aes-256-gcm:{SS_2022_KEY}@127.0.0.1:8388#SS22",
    "tcp_http_header": (
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        "?type=tcp&headerType=http&host=a.example.com&path=%2Fx&security=tls"
        "&sni=a.example.com#TH"
    ),
}


def build_config(link: str) -> dict:
    bean = parse_link(link)
    assert bean is not None, f"ссылка не разобрана: {link}"
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": 10800, "protocol": "socks", "settings": {}}],
        "outbounds": [bean.build_outbound()],
    }


@pytest.mark.parametrize("name", sorted(LINKS))
def test_generated_config_accepted_by_xray(name, tmp_path):
    config_path = tmp_path / f"{name}.json"
    config_path.write_text(json.dumps(build_config(LINKS[name])))

    result = subprocess.run(
        [str(XRAY), "-test", "-config", str(config_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert "Configuration OK" in output, output


@pytest.mark.parametrize("network", ["h2", "http"])
def test_h2_transport_reports_build_error(network):
    """Транспорт h2 ядро удалило: профиль сообщает об этом сам, не дожидаясь отказа ядра."""
    bean = parse_link(
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        f"?type={network}&security=tls&sni=a.example.com&path=%2Fh2#H2T"
    )
    assert bean is not None

    result = bean.build_core_obj_xray()

    assert "HTTP/2" in result["error"]
    assert result["outbound"] == {}
