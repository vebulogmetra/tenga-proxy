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
        """Build transport configuration for sing-box."""
        if self.network == "tcp" and self.header_type != "http":
            return None

        transport: dict[str, Any] = {"type": self.network}

        if self.network == "ws":
            if self.host:
                transport["headers"] = {"Host": self.host}

            path = self.path
            if "?ed=" in path:
                path_parts = path.split("?ed=")
                path = path_parts[0]
                try:
                    ed_length = int(path_parts[1])
                    if ed_length > 0:
                        transport["max_early_data"] = ed_length
                        transport["early_data_header_name"] = "Sec-WebSocket-Protocol"
                except ValueError:
                    pass

            if path:
                transport["path"] = path

            if self.ws_early_data_length > 0:
                transport["max_early_data"] = self.ws_early_data_length
                transport["early_data_header_name"] = self.ws_early_data_name

        elif self.network == "http":
            # HTTP/2
            if self.path:
                transport["path"] = self.path
            if self.host:
                transport["host"] = self.host.split(",")

        elif self.network == "grpc":
            if self.path:
                transport["service_name"] = self.path

        elif self.network == "httpupgrade":
            if self.path:
                transport["path"] = self.path
            if self.host:
                transport["host"] = self.host

        elif self.network == "tcp" and self.header_type == "http":
            transport = {
                "type": "http",
                "method": "GET",
            }
            if self.path:
                transport["path"] = self.path
            if self.host:
                transport["headers"] = {"Host": self.host.split(",")}

        return transport

    def build_tls(self, skip_cert: bool = False) -> dict[str, Any] | None:
        """Build TLS configuration for sing-box."""
        if self.security not in ("tls", "reality"):
            return None

        tls: dict[str, Any] = {"enabled": True}

        if self.allow_insecure or skip_cert:
            tls["insecure"] = True

        if self.sni.strip():
            tls["server_name"] = self.sni.strip()

        if self.certificate.strip():
            tls["certificate"] = self.certificate.strip()

        if self.alpn.strip():
            tls["alpn"] = [x.strip() for x in self.alpn.split(",") if x.strip()]

        # Reality
        if self.reality_public_key.strip():
            tls["reality"] = {
                "enabled": True,
                "public_key": self.reality_public_key,
                "short_id": self.reality_short_id.split(",")[0] if self.reality_short_id else "",
            }
            # Reality require uTLS
            if not self.utls_fingerprint:
                self.utls_fingerprint = "random"

        # uTLS fingerprint
        if self.utls_fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": self.utls_fingerprint}

        return tls

    def apply_to_outbound(self, outbound: dict[str, Any], skip_cert: bool = False) -> None:
        """Apply transport settings to outbound."""
        # Transport
        transport = self.build_transport()
        if transport:
            outbound["transport"] = transport
        # TLS
        tls = self.build_tls(skip_cert)
        if tls:
            outbound["tls"] = tls
        # Packet encoding for VMess/VLESS
        outbound_type = outbound.get("type", "")
        if outbound_type in ("vmess", "vless"):
            outbound["packet_encoding"] = self.packet_encoding

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
