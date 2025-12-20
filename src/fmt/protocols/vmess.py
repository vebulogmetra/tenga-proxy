from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings


@dataclass
class VMessBean(ProxyBean):
    """VMess profile."""

    uuid: str = ""
    alter_id: int = 0
    security: str = "auto"
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        return "vmess"

    # Alias
    @property
    def aid(self) -> int:
        return self.alter_id

    @aid.setter
    def aid(self, value: int) -> None:
        self.alter_id = value

    def try_parse_link(self, link: str) -> bool:
        """Parse VMess share link."""
        if not link.startswith("vmess://"):
            return False

        try:
            encoded = link[8:]
            name_from_fragment = ""

            if "#" in encoded:
                encoded, name_part = encoded.split("#", 1)
                name_from_fragment = unquote(name_part)
            # Try V2RayN format (base64 JSON)
            if self._try_parse_v2rayn_format(encoded, name_from_fragment):
                return True
            # Try Ducksoft format (URL)
            return self._try_parse_url_format(encoded, name_from_fragment)

        except Exception as e:
            print(f"Error parsing VMess link: {e}")
            return False

    def _try_parse_v2rayn_format(self, encoded: str, fallback_name: str) -> bool:
        """Parse V2RayN format (base64 JSON)."""
        try:
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding

            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
            obj = json.loads(decoded)

            self.uuid = obj.get("id", "")
            self.server_address = obj.get("add", "")
            port = obj.get("port", "")
            self.server_port = int(port) if port else 443
            self.name = obj.get("ps", fallback_name)
            self.alter_id = int(obj.get("aid", 0))
            self.stream.host = obj.get("host", "")
            self.stream.path = obj.get("path", "")
            self.stream.sni = obj.get("sni", "")
            self.stream.header_type = obj.get("type", "")

            net = obj.get("net", "")
            if net == "h2":
                net = "http"
            if net:
                self.stream.network = net

            scy = obj.get("scy", "")
            if scy:
                self.security = scy

            self.stream.security = obj.get("tls", "")

            return bool(self.uuid and self.server_address)
        except:
            return False

    def _try_parse_url_format(self, encoded: str, fallback_name: str) -> bool:
        """Parse Ducksoft format (URL)."""
        try:
            url = urlparse("vmess://" + encoded)
            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port or 443
            self.uuid = url.username or ""
            self.name = fallback_name

            if url.fragment:
                self.name = unquote(url.fragment)

            self.alter_id = 0
            self.security = "auto"

            query = parse_qs(url.query)

            # Encryption
            if "encryption" in query:
                self.security = query["encryption"][0]
            # Security/TLS
            security = query.get("security", ["tls"])[0]
            if security == "reality":
                security = "tls"
            self.stream.security = security
            # Network type
            net_type = query.get("type", ["tcp"])[0]
            if net_type == "h2":
                net_type = "http"
            self.stream.network = net_type
            # SNI
            if "sni" in query:
                self.stream.sni = query["sni"][0]
            # Allow insecure
            if "allowInsecure" in query:
                self.stream.allow_insecure = True
            # uTLS fingerprint
            self.stream.utls_fingerprint = query.get("fp", [""])[0]
            # Reality
            if "pbk" in query:
                self.stream.reality_public_key = query["pbk"][0]
            if "sid" in query:
                self.stream.reality_short_id = query["sid"][0]
            if "spx" in query:
                self.stream.reality_spider_x = query["spx"][0]
            # Transport settings
            self._parse_transport_settings(query)

            return bool(self.uuid and self.server_address)
        except:
            return False

    def _parse_transport_settings(self, query: dict[str, list]) -> None:
        """Parse transport settings."""
        if self.stream.network in ("ws", "http", "httpupgrade"):
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

    def to_share_link(self, use_old_format: bool = False) -> str:
        """Create VMess share link."""
        if use_old_format:
            return self._to_v2rayn_link()
        return self._to_url_link()

    def _to_v2rayn_link(self) -> str:
        """V2RayN format."""
        obj = {
            "v": "2",
            "ps": self.name,
            "add": self.server_address,
            "port": str(self.server_port),
            "id": self.uuid,
            "aid": str(self.alter_id),
            "net": self.stream.network,
            "host": self.stream.host,
            "path": self.stream.path,
            "type": self.stream.header_type,
            "scy": self.security,
            "tls": self.stream.security if self.stream.security == "tls" else "",
            "sni": self.stream.sni,
        }
        json_str = json.dumps(obj, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8").rstrip("=")
        return f"vmess://{encoded}"

    def _to_url_link(self) -> str:
        """Ducksoft URL format."""
        url = f"vmess://{self.uuid}@{self.server_address}:{self.server_port}"

        query_params = {"encryption": self.security}

        security = self.stream.security
        if security == "tls" and self.stream.reality_public_key:
            security = "reality"
        query_params["security"] = security or "none"

        if self.stream.sni:
            query_params["sni"] = self.stream.sni
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

        query_params["type"] = self.stream.network

        # Transport params
        if self.stream.network in ("ws", "http", "xhttp", "httpupgrade"):
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
                if self.stream.host:
                    query_params["host"] = self.stream.host
                if self.stream.path:
                    query_params["path"] = self.stream.path

        if query_params:
            url += "?" + urlencode(query_params)

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core."""
        outbound: dict[str, Any] = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": self.server_address,
                        "port": self.server_port,
                        "users": [
                            {
                                "id": self.uuid.strip(),
                                "alterId": self.alter_id,
                                "security": self.security,
                            }
                        ],
                    }
                ]
            },
        }

        if self.name:
            outbound["tag"] = self.name

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound
