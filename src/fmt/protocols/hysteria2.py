from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings, parse_json_object


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

        if query_params:
            url += "?" + urlencode(query_params)

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core.

        Схема сверена с `core/bin/xray -test`: у этого форка настройки клиента
        плоские (address/port/auth), а не список `servers[]`, и обязателен
        `version: 2` — без него ядро падает с `version != 2`.
        """
        settings: dict[str, Any] = {
            "address": self.server_address,
            "port": self.server_port,
            "auth": self.auth,
            "version": self.HYSTERIA_VERSION,
        }

        if self.obfs:
            settings["obfs"] = self.obfs
            if self.obfs_password:
                settings["password"] = self.obfs_password

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

        # fm из share-ссылки — готовое тело finalmask. Кладём как есть: разбирать
        # по полям нельзя, набор масок у форка открытый.
        final_mask = parse_json_object(self.final_mask)
        if final_mask:
            stream_settings["finalmask"] = final_mask

        return outbound
