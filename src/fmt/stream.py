from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.db.config import ConfigBase


@dataclass
class StreamSettings(ConfigBase):
    """Transport settings (TLS, WebSocket, gRPC, etc.)."""

    # Network/Transport
    network: str = "tcp"  # tcp, ws, http, grpc, httpupgrade, quic
    path: str = ""
    host: str = ""
    header_type: str = ""  # For TCP with HTTP header
    # TLS
    security: str = ""  # tls, reality, none
    sni: str = ""
    alpn: str = ""
    allow_insecure: bool = False
    certificate: str = ""
    utls_fingerprint: str = ""
    # Reality
    reality_public_key: str = ""  # reality_pbk
    reality_short_id: str = ""  # reality_sid
    reality_spider_x: str = ""  # reality_spx
    # WebSocket Early Data
    ws_early_data_length: int = 0
    ws_early_data_name: str = "Sec-WebSocket-Protocol"
    # Packet encoding
    packet_encoding: str = "xudp"  # Для VMess/VLESS

    def build_transport(self) -> dict[str, Any] | None:
        """Build transport configuration for xray-core (streamSettings)."""
        if self.network == "tcp" and self.header_type != "http":
            return None

        transport_type = self.network

        stream_settings: dict[str, Any] = {"network": transport_type}

        if transport_type == "ws":
            ws_settings: dict[str, Any] = {}
            if self.path:
                ws_settings["path"] = self.path
            if self.host:
                ws_settings["headers"] = {"Host": self.host}
            if self.ws_early_data_length > 0:
                ws_settings["maxEarlyData"] = self.ws_early_data_length
                ws_settings["earlyDataHeaderName"] = self.ws_early_data_name
            path = self.path
            if "?ed=" in path:
                path_parts = path.split("?ed=")
                path = path_parts[0]
                ws_settings["path"] = path
                try:
                    ed_length = int(path_parts[1])
                    if ed_length > 0:
                        ws_settings["maxEarlyData"] = ed_length
                        ws_settings["earlyDataHeaderName"] = "Sec-WebSocket-Protocol"
                except ValueError:
                    pass
            if ws_settings:
                stream_settings["wsSettings"] = ws_settings

        elif transport_type == "http":
            # HTTP/2
            http_settings: dict[str, Any] = {}
            if self.path:
                http_settings["path"] = self.path
            if self.host:
                http_settings["host"] = self.host.split(",")
            if http_settings:
                stream_settings["httpSettings"] = http_settings

        elif transport_type == "xhttp":
            stream_settings["network"] = "splithttp"
            splithttp_settings: dict[str, Any] = {}

            if self.path and self.path.strip() and self.path.strip() != "/":
                splithttp_settings["path"] = self.path.strip()
            host_value = None
            if self.host:
                if isinstance(self.host, str):
                    host_parts = [h.strip() for h in self.host.split(",") if h.strip()]
                    if host_parts:
                        host_value = host_parts[0]
                elif isinstance(self.host, list):
                    if self.host:
                        host_value = str(self.host[0])
            if not host_value and self.sni:
                host_value = self.sni.strip()
            if host_value:
                splithttp_settings["host"] = host_value
            stream_settings["splithttpSettings"] = splithttp_settings

        elif transport_type == "grpc":
            grpc_settings: dict[str, Any] = {}
            if self.path:
                grpc_settings["serviceName"] = self.path
            if grpc_settings:
                stream_settings["grpcSettings"] = grpc_settings

        elif transport_type == "httpupgrade":
            httpupgrade_settings: dict[str, Any] = {}
            if self.path:
                httpupgrade_settings["path"] = self.path
            if self.host:
                httpupgrade_settings["host"] = self.host
            if httpupgrade_settings:
                stream_settings["httpupgradeSettings"] = httpupgrade_settings

        elif self.network == "tcp" and self.header_type == "http":
            stream_settings["network"] = "http"
            http_settings: dict[str, Any] = {}
            if self.path:
                http_settings["path"] = self.path
            if self.host:
                http_settings["host"] = self.host.split(",")
            if http_settings:
                stream_settings["httpSettings"] = http_settings

        return stream_settings

    def build_tls(self, skip_cert: bool = False) -> dict[str, Any] | None:
        """Build TLS configuration for xray-core."""
        if self.security not in ("tls", "reality"):
            return None

        tls_settings: dict[str, Any] = {}

        if self.allow_insecure or skip_cert:
            tls_settings["allowInsecure"] = True

        if self.sni.strip():
            tls_settings["serverName"] = self.sni.strip()

        if self.certificate.strip():
            # xray-core uses certificates array
            tls_settings["certificates"] = [{"certificate": self.certificate.strip()}]

        if self.alpn.strip():
            tls_settings["alpn"] = [x.strip() for x in self.alpn.split(",") if x.strip()]

        # uTLS fingerprint
        if self.utls_fingerprint:
            tls_settings["fingerprint"] = self.utls_fingerprint

        return tls_settings

    def build_reality(self) -> dict[str, Any] | None:
        """Build Reality configuration for xray-core."""
        if not self.reality_public_key.strip():
            return None

        reality_settings: dict[str, Any] = {
            "show": False,
        }

        if self.sni.strip():
            reality_settings["serverName"] = self.sni.strip()

        if self.reality_public_key:
            reality_settings["publicKey"] = self.reality_public_key

        if self.reality_short_id:
            reality_settings["shortId"] = self.reality_short_id.split(",")[0]

        if self.reality_spider_x:
            reality_settings["spiderX"] = self.reality_spider_x

        # uTLS fingerprint (required for Reality)
        if self.utls_fingerprint:
            reality_settings["fingerprint"] = self.utls_fingerprint
        else:
            reality_settings["fingerprint"] = "chrome"

        return reality_settings

    def is_reality(self) -> bool:
        """Check if Reality is enabled."""
        return bool(self.reality_public_key.strip())

    def apply_to_outbound(self, outbound: dict[str, Any], skip_cert: bool = False) -> None:
        """Apply transport settings to outbound."""
        stream_settings = self.build_transport()

        if stream_settings is None:
            stream_settings = {}

        # Check if Reality is used
        if self.is_reality():
            reality = self.build_reality()
            if reality:
                stream_settings["security"] = "reality"
                stream_settings["realitySettings"] = reality
        else:
            tls = self.build_tls(skip_cert)
            if tls:
                stream_settings["security"] = self.security
                stream_settings["tlsSettings"] = tls

        if stream_settings:
            outbound["streamSettings"] = stream_settings

        outbound_type = outbound.get("protocol", "")
        if outbound_type in ("vmess", "vless"):
            if "settings" not in outbound:
                outbound["settings"] = {}
            outbound["settings"]["packetEncoding"] = self.packet_encoding

    # Aliases
    @property
    def reality_pbk(self) -> str:
        return self.reality_public_key

    @reality_pbk.setter
    def reality_pbk(self, value: str) -> None:
        self.reality_public_key = value

    @property
    def reality_sid(self) -> str:
        return self.reality_short_id

    @reality_sid.setter
    def reality_sid(self, value: str) -> None:
        self.reality_short_id = value

    @property
    def reality_spx(self) -> str:
        return self.reality_spider_x

    @reality_spx.setter
    def reality_spx(self, value: str) -> None:
        self.reality_spider_x = value


V2RayStreamSettings = StreamSettings
