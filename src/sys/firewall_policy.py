"""Описание блокировки трафика мимо туннеля, без привязки к ОС.

Метку ставит и сборщик конфига ядра, и правило `meta mark` помощника, поэтому
модуль лежит отдельно от реализаций и ничего не тянет за собой.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Метка сокетов ядра: её же ждёт правило `meta mark` в tun_route_helper.sh.
SOCKET_MARK = 0x7E6A


class Level(StrEnum):
    IPV6_ONLY = "ipv6_only"
    FULL = "full"


@dataclass(frozen=True)
class FirewallPolicy:
    level: Level
    tun_name: str
    vpn_interface: str | None = None
    vpn_addresses: tuple[str, ...] = ()
    dns_closed: bool = False
    # DNS сети: пока окно открыто, до него можно достучаться и вне локальных адресов.
    dns_addresses: tuple[str, ...] = ()

    def helper_args(self) -> list[str]:
        args = [
            str(self.level),
            self.tun_name,
            self.vpn_interface or "-",
            ",".join(self.vpn_addresses) or "-",
            "closed" if self.dns_closed else "open",
        ]
        if self.dns_addresses and not self.dns_closed:
            args.append(",".join(self.dns_addresses))
        return args
