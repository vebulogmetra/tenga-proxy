"""Проверка сгенерированных конфигов настоящим бинарником xray.

Юнит-тесты подтверждают только внутреннюю согласованность Python-кода: схему
конфига знает лишь ядро. Эти тесты ловят расхождение со схемой форка — например,
`network: "udp"` или настройки в виде `servers[]`, которые ядро молча не принимает.
"""

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

FM = quote('{"salamander":{"password":"secret"}}')
EXTRA = quote('{"scMaxEachPostBytes":1000000,"xmux":{"maxConcurrency":"16-32"},"seqKey":"abc"}')

LINKS = {
    "hysteria2": (
        "hysteria2://pass123@127.0.0.1:8443"
        f"?sni=cdn.example.com&alpn=h3&obfs=salamander&obfs-password=obfspass&fm={FM}#H2"
    ),
    "hysteria2_plain": "hysteria2://pass123@127.0.0.1:8443#H2",
    "xhttp": (
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        f"?type=xhttp&security=tls&sni=a.example.com&mode=stream-one"
        f"&xPaddingBytes=100-1000&extra={EXTRA}#X"
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
