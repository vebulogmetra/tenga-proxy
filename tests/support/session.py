"""Общие заготовки тестов сборки конфига сессии."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.core.context import AppContext, init_context
from src.db.config import RoutingMode
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
BUNDLED_GEO_DIR = XRAY.parent.resolve()

VLESS_LINK = (
    "vless://11111111-1111-1111-1111-111111111111@proxy.example.org:443"
    "?type=tcp&security=tls&sni=proxy.example.org#Test"
)


def use_bundled_geo(monkeypatch) -> None:
    """Направить и сборщик, и `xray -test` на геобазы из core/bin.

    Без этого каталог зависел бы от того, какой бинарник найдёт приложение, а
    `tests/test_core_config.py` перезагружает модуль путей с чужим каталогом.
    """
    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(BUNDLED_GEO_DIR))


def make_context(tmp_path: Path) -> AppContext:
    return init_context(config_dir=tmp_path)


def make_profile(context: AppContext, link: str = VLESS_LINK) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None
    entry = ProfileEntry(id=1, group_id=0, bean=bean)
    context.profiles.profiles[1] = entry
    return entry


def use_custom_lists(context: AppContext, **lists: list[str]) -> None:
    """Включить режим списков и записать их на диск: сборщик читает списки из файлов."""
    routing = context.config.routing
    routing.mode = RoutingMode.CUSTOM
    for name, entries in lists.items():
        setattr(routing, f"{name}_list", list(entries))
    routing.save_lists_to_files(context.config_dir)


def rules_to(config: dict, outbound_tag: str) -> list[dict]:
    return [r for r in config["routing"]["rules"] if r.get("outboundTag") == outbound_tag]


def rule_values(config: dict, outbound_tag: str, key: str) -> list[str]:
    return [value for rule in rules_to(config, outbound_tag) for value in rule.get(key, [])]


def with_socks_inbound(config: dict) -> dict:
    """Тот же конфиг, но вместо TUN — SOCKS с тем же тегом.

    `xray -test` на TUN-inbound пытается создать интерфейс, а на машине
    разработчика он занят рабочим подключением. Правила с `inboundTag` при этом
    проверяются так же: ядру важен тег, а не протокол входа.
    """
    copy = json.loads(json.dumps(config))
    for index, inbound in enumerate(copy["inbounds"]):
        if inbound.get("protocol") == "tun":
            copy["inbounds"][index] = {
                "tag": inbound.get("tag", "tun-in"),
                "listen": "127.0.0.1",
                "port": 10800 + index,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
    return copy


def xray_verdict(config: dict, tmp_path: Path) -> str:
    """Вывод `xray -test` для конфига; «Configuration OK» — принят."""
    assert not any(i.get("protocol") == "tun" for i in config["inbounds"]), (
        "TUN-конфиг настоящему ядру не отдаём: см. with_socks_inbound"
    )
    path = tmp_path / "session.json"
    path.write_text(json.dumps(config))
    result = subprocess.run(
        [str(XRAY), "-test", "-config", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout + result.stderr
