from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings, parse_json_object

# Мультипорт в authority: `host:443,20000-50000` или `host:20000-50000`.
_MULTI_PORT_AUTHORITY = re.compile(
    r"^(.+):(\d{1,5}(?:-\d{1,5})?(?:,\d{1,5}(?:-\d{1,5})?)+|\d{1,5}-\d{1,5})$"
)
_PORT_SPEC = re.compile(r"^\d{1,5}(?:-\d{1,5})?(?:,\d{1,5}(?:-\d{1,5})?)*$")
_HOP_INTERVAL = re.compile(r"^(\d{1,4})(?:-(\d{1,4}))?$")
# Меньший интервал ядро отвергает («invalid interval»), причём только при dial.
MIN_HOP_INTERVAL_SEC = 5
# Значение официального клиента Hysteria.
DEFAULT_HOP_INTERVAL_SEC = "30"


def _is_valid_port_spec(spec: str) -> bool:
    """Спецификация портов xray: `443,20000-50000`."""
    if not _PORT_SPEC.match(spec):
        return False
    for part in spec.split(","):
        bounds = [int(x) for x in part.split("-")]
        if not all(1 <= b <= 65535 for b in bounds) or bounds[0] > bounds[-1]:
            return False
    return True


def _is_valid_hop_interval(value: str) -> bool:
    """Секунды: `30` или диапазон `20-40`."""
    match = _HOP_INTERVAL.match(value)
    if not match:
        return False
    low = int(match.group(1))
    high = int(match.group(2) or match.group(1))
    return MIN_HOP_INTERVAL_SEC <= low <= high


def _positive_int(value: str) -> int:
    return int(value) if value.isdigit() and int(value) > 0 else 0


@dataclass
class Hysteria2Bean(ProxyBean):
    """Профиль hysteria2 (QUIC).

    Поддержан форком xray-core из `core/bin/xray` (`proxy/hysteria`): в конфиг идёт
    `protocol: "hysteria"` — не "hysteria2", как в схеме sing-box. Учётка лежит в
    `settings.servers[].auth`, обфускация — в `streamSettings.finalmask`.
    """

    # Ядро принимает только hysteria2: при другом значении падает с `version != 2`.
    HYSTERIA_VERSION: ClassVar[int] = 2
    # Имя транспорта в streamSettings.network для форка xray-core.
    HYSTERIA_NETWORK: ClassVar[str] = "hysteria"

    auth: str = ""
    obfs: str = ""
    obfs_password: str = ""
    # Сырой JSON из `?fm={...}` — тело streamSettings.finalmask. Хранится строкой
    # намеренно: масок у форка целое семейство (salamander, sudoku, fragment, noise,
    # mkcp), набор ключей открытый и меняется от сервера к серверу.
    final_mask: str = ""
    # Port hopping (маска udphop). hop_ports — спецификация портов xray.
    hop_ports: str = ""
    # Секунды, "30" или "20-40"; пусто — DEFAULT_HOP_INTERVAL_SEC.
    hop_interval: str = ""
    # brutal (finalmask.quicParams), Мбит/с. 0 — не задано, решает ядро.
    up_mbps: int = 0
    down_mbps: int = 0
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        return "hysteria2"

    @property
    def password(self) -> str:
        return self.auth

    @password.setter
    def password(self, value: str) -> None:
        self.auth = value

    def try_parse_link(self, link: str) -> bool:
        """Parse hysteria2 share link."""
        lower = link.lower()
        if not lower.startswith(("hysteria2://", "hy2://")):
            return False

        try:
            url = urlparse(link)

            # Официальный формат допускает мультипорт в authority. urlparse на нём
            # бросает при чтении port, поэтому отрезаем спецификацию сами: первый
            # порт — основной, вся спецификация — диапазон для хопа.
            userinfo, _, hostport = url.netloc.rpartition("@")
            multi_port = _MULTI_PORT_AUTHORITY.match(hostport)
            hop_ports = ""
            if multi_port:
                spec = multi_port.group(2)
                first_port = re.split("[,-]", spec)[0]
                url = url._replace(netloc=f"{userinfo}@{multi_port.group(1)}:{first_port}")
                if _is_valid_port_spec(spec):
                    hop_ports = spec

            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port or 443
            self.auth = unquote(url.username or "")

            if url.fragment:
                self.name = unquote(url.fragment)

            query = parse_qs(url.query)

            # hysteria2 всегда поверх TLS — отдельного security в ссылке нет.
            # network именно "hysteria": транспорт "udp" ядро отвергает
            # с `unknown transport protocol: udp`.
            self.stream.network = self.HYSTERIA_NETWORK
            self.stream.security = "tls"

            sni = query.get("sni", [""])[0] or query.get("peer", [""])[0]
            if sni:
                self.stream.sni = sni
            if "alpn" in query:
                self.stream.alpn = query["alpn"][0]
            if query.get("insecure", [""])[0] in ("1", "true"):
                self.stream.allow_insecure = True

            self.obfs = query.get("obfs", [""])[0]
            self.obfs_password = query.get("obfs-password", [""])[0]

            mport = query.get("mport", [""])[0]
            if _is_valid_port_spec(mport):
                hop_ports = mport
            self.hop_ports = hop_ports
            hop_interval = query.get("hop-interval", [""])[0] or query.get("hopInterval", [""])[0]
            self.hop_interval = hop_interval if _is_valid_hop_interval(hop_interval) else ""
            self.up_mbps = _positive_int(query.get("upmbps", [""])[0])
            self.down_mbps = _positive_int(query.get("downmbps", [""])[0])

            # Битый fm отбрасываем, а не роняем всю ссылку: try_parse_link не бросает.
            fm = query.get("fm", [""])[0]
            if fm and parse_json_object(fm):
                self.final_mask = fm

            return bool(self.auth and self.server_address)

        except Exception as e:
            print(f"Error parsing hysteria2 link: {e}")
            return False

    def to_share_link(self) -> str:
        """Create hysteria2 share link."""
        url = f"hysteria2://{quote(self.auth, safe='')}@{self.server_address}:{self.server_port}"

        query_params: dict[str, str] = {}
        if self.stream.sni:
            query_params["sni"] = self.stream.sni
        if self.stream.alpn:
            query_params["alpn"] = self.stream.alpn
        if self.stream.allow_insecure:
            query_params["insecure"] = "1"
        if self.obfs:
            query_params["obfs"] = self.obfs
        if self.obfs_password:
            query_params["obfs-password"] = self.obfs_password
        # Без fm пересобранная ссылка теряет обфускацию и профиль перестаёт работать.
        if self.final_mask:
            query_params["fm"] = self.final_mask
        # В authority пишем только основной порт: одиночный порт другие клиенты
        # разбирают надёжнее, диапазон уходит в mport.
        if self.hop_ports:
            query_params["mport"] = self.hop_ports
        if self.hop_interval:
            query_params["hop-interval"] = self.hop_interval
        if self.up_mbps > 0:
            query_params["upmbps"] = str(self.up_mbps)
        if self.down_mbps > 0:
            query_params["downmbps"] = str(self.down_mbps)

        if query_params:
            url += "?" + urlencode(query_params)

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core.

        Схема сверена с исходником форка (`infra/conf/hysteria.go`,
        `infra/conf/transport_method.go`):

        - `HysteriaClientConfig{Version, Address, Port}` — адрес плоский, без
          `servers[]`: со списком `Address` остаётся nil и `Address.Build()`
          роняет процесс нативной паникой, а не возвращает ошибку конфига;
        - `auth` живёт в `streamSettings.hysteriaSettings`; в `settings` это
          поле принадлежит `HysteriaServerConfig` и клиентом не читается;
        - `obfs`/`password`/`congestion`/`up`/`down` в клиентском конфиге
          отсутствуют — обфускация задаётся только через `finalmask`;
        - `version: 2` обязателен в обоих блоках, иначе `version != 2`.
        """
        settings: dict[str, Any] = {
            "version": self.HYSTERIA_VERSION,
            "address": self.server_address,
            "port": self.server_port,
        }

        outbound: dict[str, Any] = {
            "protocol": "hysteria",
            "settings": settings,
        }

        if self.name:
            outbound["tag"] = self.name

        self.stream.apply_to_outbound(outbound, skip_cert)

        stream_settings = outbound.setdefault("streamSettings", {})
        # Транспорт hysteria требует своих version/auth — отдельно от settings.
        stream_settings["hysteriaSettings"] = {
            "version": self.HYSTERIA_VERSION,
            "auth": self.auth,
        }

        final_mask = self._build_final_mask()
        if final_mask:
            stream_settings["finalmask"] = final_mask

        return outbound

    def _build_final_mask(self) -> dict[str, Any]:
        """Собрать тело `streamSettings.finalmask`.

        Основа — сырой `?fm=`: это готовое тело от провайдера, набор масок у
        ядра открытый и разбирать его по полям нельзя. Поверх него достраиваем
        маски из явных параметров ссылки; тип, который в `fm` уже есть, не
        дублируем, а ключи `quicParams` из `fm` не перезаписываем.

        Формат именно `{"udp": [{"type": ..., "settings": {...}}]}` (conf.FinalMask →
        `Tcp`/`Udp []Mask`, Mask = {type, settings}); плоскую форму
        `{"salamander": {...}}` ядро молча игнорирует — обфускации не будет,
        а ошибки в конфиге не увидишь.
        """
        mask = parse_json_object(self.final_mask)
        fm_udp = mask.get("udp")
        if not isinstance(fm_udp, list):
            fm_udp = []
        fm_types = {m.get("type") for m in fm_udp if isinstance(m, dict)}

        udp: list[Any] = []
        # udphop обязан стоять первым («outermost level»): иначе ядро падает при
        # dial, а не при сборке конфига — `xray -test` этого не увидит.
        if self.hop_ports and "udphop" not in fm_types:
            udp.append(
                {
                    "type": "udphop",
                    "settings": {
                        # Как у официального клиента: новый сокет и порт на каждом хопе.
                        "mode": "intervalLocal,intervalRemote",
                        "interval": self.hop_interval or DEFAULT_HOP_INTERVAL_SEC,
                        "remotePorts": self.hop_ports,
                    },
                }
            )
        # Готовый udphop тоже должен быть снаружи: сохраняем его настройки
        # провайдера и порядок остальных масок.
        udp.extend(m for m in fm_udp if isinstance(m, dict) and m.get("type") == "udphop")
        udp.extend(m for m in fm_udp if not isinstance(m, dict) or m.get("type") != "udphop")
        # Только salamander: остальные udp-маски не описываются парой
        # obfs/obfs-password, а неизвестный type ядро отвергает вместе со всем
        # конфигом — молча пропускаем, как и любой неразобранный параметр.
        if self.obfs == "salamander" and "salamander" not in fm_types:
            udp.append({"type": "salamander", "settings": {"password": self.obfs_password}})
        if udp:
            mask["udp"] = udp

        if self.up_mbps > 0:
            quic = mask.get("quicParams")
            quic = dict(quic) if isinstance(quic, dict) else {}
            quic.setdefault("congestion", "brutal")
            quic.setdefault("brutalUp", f"{self.up_mbps} mbps")
            if self.down_mbps > 0:
                quic.setdefault("brutalDown", f"{self.down_mbps} mbps")
            mask["quicParams"] = quic

        return mask
