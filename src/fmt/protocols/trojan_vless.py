from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings


@dataclass
class VLESSBean(ProxyBean):
    """VLESS profile."""

    uuid: str = ""
    flow: str = ""
    encryption: str = "none"
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        return "vless"

    @property
    def password(self) -> str:
        return self.uuid

    @password.setter
    def password(self, value: str) -> None:
        self.uuid = value

    def try_parse_link(self, link: str) -> bool:
        """Parse VLESS share link."""
        if not link.startswith("vless://"):
            return False

        try:
            url = urlparse(link)
            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port or 443
            self.uuid = url.username or ""

            if url.fragment:
                self.name = unquote(url.fragment)

            query = parse_qs(url.query)
            # Network type
            net_type = query.get("type", ["tcp"])[0]
            if net_type == "h2":
                net_type = "http"
            self.stream.network = net_type

            # Security
            security = query.get("security", [""])[0]
            if security == "reality":
                security = "tls"
            elif security == "none":
                security = ""
            self.stream.security = security
            # SNI
            sni = query.get("sni", [""])[0] or query.get("peer", [""])[0]
            if sni:
                self.stream.sni = sni
            # ALPN
            if "alpn" in query:
                self.stream.alpn = query["alpn"][0]
            # Allow insecure
            if "allowInsecure" in query:
                self.stream.allow_insecure = True
            # Reality
            if "pbk" in query:
                self.stream.reality_public_key = query["pbk"][0]
            if "sid" in query:
                self.stream.reality_short_id = query["sid"][0]
            if "spx" in query:
                self.stream.reality_spider_x = query["spx"][0]
            # uTLS fingerprint
            self.stream.utls_fingerprint = query.get("fp", [""])[0]
            if "encryption" in query:
                self.encryption = query["encryption"][0]
            else:
                self.encryption = "none"
            # Transport settings
            self._parse_transport_settings(query)
            # Flow
            if "flow" in query:
                self.flow = query["flow"][0]

            return bool(self.uuid and self.server_address)

        except Exception as e:
            print(f"Error parsing VLESS link: {e}")
            return False

    def _parse_transport_settings(self, query: dict[str, list]) -> None:
        """Parse transport settings from query parameters."""
        if self.stream.network == "ws":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0]
        elif self.stream.network == "http":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0].replace("|", ",")
        elif self.stream.network == "httpupgrade":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0]
        elif self.stream.network == "grpc":
            if "serviceName" in query:
                self.stream.path = query["serviceName"][0]
        elif self.stream.network == "tcp":
            if query.get("headerType", [""])[0] == "http":
                self.stream.header_type = "http"
                if "host" in query:
                    self.stream.host = query["host"][0]
                if "path" in query:
                    self.stream.path = query["path"][0]

    def to_share_link(self) -> str:
        """Create VLESS share link."""
        url = f"vless://{self.uuid}@{self.server_address}:{self.server_port}"

        query_params = {}

        # Security
        security = self.stream.security
        if security == "tls" and self.stream.reality_public_key:
            security = "reality"
        query_params["security"] = security or "none"

        if self.stream.sni:
            query_params["sni"] = self.stream.sni
        if self.stream.alpn:
            query_params["alpn"] = self.stream.alpn
        if self.stream.allow_insecure:
            query_params["allowInsecure"] = "1"
        if self.stream.utls_fingerprint:
            query_params["fp"] = self.stream.utls_fingerprint

        if security == "reality":
            query_params["pbk"] = self.stream.reality_public_key
            if self.stream.reality_short_id:
                query_params["sid"] = self.stream.reality_short_id
            if self.stream.reality_spider_x:
                query_params["spx"] = self.stream.reality_spider_x

        # Network type
        query_params["type"] = self.stream.network

        self._add_transport_params(query_params)
        # Flow
        if self.flow:
            query_params["flow"] = self.flow
        # Encryption
        if self.encryption and self.encryption != "none":
            query_params["encryption"] = self.encryption

        if query_params:
            url += "?" + urlencode(query_params)

        if self.name:
            url += "#" + quote(self.name)

        return url

    def _add_transport_params(self, params: dict[str, str]) -> None:
        """Add transport parameters."""
        if self.stream.network in ("ws", "http", "httpupgrade"):
            if self.stream.path:
                params["path"] = self.stream.path
            if self.stream.host:
                params["host"] = self.stream.host
        elif self.stream.network == "grpc":
            if self.stream.path:
                params["serviceName"] = self.stream.path
        elif self.stream.network == "tcp":
            if self.stream.header_type == "http":
                params["headerType"] = "http"
                if self.stream.path:
                    params["path"] = self.stream.path
                if self.stream.host:
                    params["host"] = self.stream.host

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core."""
        flow = self.flow
        if flow.endswith("-udp443"):
            flow = flow[:-7]
        elif flow == "none":
            flow = ""

        outbound: dict[str, Any] = {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": self.server_address,
                        "port": self.server_port,
                        "users": [
                            {
                                "id": self.uuid.strip(),
                                "encryption": self.encryption or "none",
                            }
                        ],
                    }
                ]
            },
        }

        if flow:
            outbound["settings"]["vnext"][0]["users"][0]["flow"] = flow

        if self.name:
            outbound["tag"] = self.name

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound


@dataclass
class TrojanBean(ProxyBean):
    """Trojan profile."""

    password: str = ""
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        return "trojan"

    def try_parse_link(self, link: str) -> bool:
        """Parse Trojan share link."""
        if not link.startswith("trojan://"):
            return False

        try:
            url = urlparse(link)
            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port or 443
            self.password = url.username or ""

            if url.fragment:
                self.name = unquote(url.fragment)

            query = parse_qs(url.query)
            # Network type
            net_type = query.get("type", ["tcp"])[0]
            if net_type == "h2":
                net_type = "http"
            if net_type == "xhttp":
                net_type = "http"
            self.stream.network = net_type
            # Security - Trojan uses TLS by default
            security = query.get("security", ["tls"])[0]
            if security == "reality":
                security = "tls"
            elif security == "none":
                security = ""
            self.stream.security = security
            # SNI
            sni = query.get("sni", [""])[0] or query.get("peer", [""])[0]
            if sni:
                self.stream.sni = sni
            # ALPN
            if "alpn" in query:
                self.stream.alpn = query["alpn"][0]
            # Allow insecure
            if "allowInsecure" in query:
                self.stream.allow_insecure = True
            # Reality
            if "pbk" in query:
                self.stream.reality_public_key = query["pbk"][0]
            if "sid" in query:
                self.stream.reality_short_id = query["sid"][0]
            if "spx" in query:
                self.stream.reality_spider_x = query["spx"][0]
            # uTLS fingerprint
            self.stream.utls_fingerprint = query.get("fp", [""])[0]
            # Transport settings - reuse VLESS logic
            self._parse_transport_settings(query)

            return bool(self.password and self.server_address)

        except Exception as e:
            print(f"Error parsing Trojan link: {e}")
            return False

    def _parse_transport_settings(self, query: dict[str, list]) -> None:
        """Parse transport settings."""
        if self.stream.network == "ws":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0]
        elif self.stream.network == "http":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0].replace("|", ",")
        elif self.stream.network == "httpupgrade":
            if "path" in query:
                self.stream.path = query["path"][0]
            if "host" in query:
                self.stream.host = query["host"][0]
        elif self.stream.network == "grpc":
            if "serviceName" in query:
                self.stream.path = query["serviceName"][0]
        elif self.stream.network == "tcp":
            if query.get("headerType", [""])[0] == "http":
                self.stream.header_type = "http"
                if "host" in query:
                    self.stream.host = query["host"][0]
                if "path" in query:
                    self.stream.path = query["path"][0]

    def to_share_link(self) -> str:
        """Create Trojan share link."""
        url = f"trojan://{self.password}@{self.server_address}:{self.server_port}"

        query_params = {}

        # Security
        security = self.stream.security or "tls"
        if security == "tls" and self.stream.reality_public_key:
            security = "reality"
        query_params["security"] = security

        if self.stream.sni:
            query_params["sni"] = self.stream.sni
        if self.stream.alpn:
            query_params["alpn"] = self.stream.alpn
        if self.stream.allow_insecure:
            query_params["allowInsecure"] = "1"
        if self.stream.utls_fingerprint:
            query_params["fp"] = self.stream.utls_fingerprint

        if security == "reality":
            query_params["pbk"] = self.stream.reality_public_key
            if self.stream.reality_short_id:
                query_params["sid"] = self.stream.reality_short_id
            if self.stream.reality_spider_x:
                query_params["spx"] = self.stream.reality_spider_x
        # Network type
        query_params["type"] = self.stream.network
        # Transport params
        if self.stream.network in ("ws", "http", "httpupgrade"):
            if self.stream.path:
                query_params["path"] = self.stream.path
            if self.stream.host:
                query_params["host"] = self.stream.host
        elif self.stream.network == "grpc":
            if self.stream.path:
                query_params["serviceName"] = self.stream.path
        elif self.stream.network == "tcp":
            if self.stream.header_type == "http":
                query_params["headerType"] = "http"
                if self.stream.path:
                    query_params["path"] = self.stream.path
                if self.stream.host:
                    query_params["host"] = self.stream.host

        if query_params:
            url += "?" + urlencode(query_params)

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core."""
        outbound: dict[str, Any] = {
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": self.server_address,
                        "port": self.server_port,
                        "password": self.password,
                    }
                ]
            },
        }

        if self.name:
            outbound["tag"] = self.name

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound


class TrojanVLESSBean:
    """Factory class for compatibility."""

    PROXY_TROJAN = 0
    PROXY_VLESS = 1

    def __new__(cls, proxy_type: int = PROXY_TROJAN) -> ProxyBean:
        if proxy_type == cls.PROXY_VLESS:
            return VLESSBean()
        return TrojanBean()
