from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings


class SocksType:
    """SOCKS protocol types."""

    SOCKS4 = 0
    SOCKS4A = 1
    SOCKS5 = 2
    HTTP = 3


@dataclass
class SocksBean(ProxyBean):
    """SOCKS profile."""

    username: str = ""
    password: str = ""
    socks_version: int = SocksType.SOCKS5
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        if self.socks_version == SocksType.SOCKS4:
            return "socks4"
        if self.socks_version == SocksType.SOCKS4A:
            return "socks4a"
        return "socks5"

    def try_parse_link(self, link: str) -> bool:
        """Parse SOCKS share link."""
        if link.startswith("socks4a://"):
            self.socks_version = SocksType.SOCKS4A
        elif link.startswith("socks4://"):
            self.socks_version = SocksType.SOCKS4
        elif link.startswith("socks://") or link.startswith("socks5://"):
            self.socks_version = SocksType.SOCKS5
        else:
            return False

        return self._parse_url(link)

    def _parse_url(self, link: str) -> bool:
        """Parse URL."""
        try:
            url = urlparse(link)
            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port if url.port and url.port != -1 else 1080

            self.username = url.username or ""
            self.password = url.password or ""

            if url.fragment:
                self.name = unquote(url.fragment)

            # v2rayN format: username contains base64 encoded user:pass
            if not self.password and self.username:
                try:
                    padding = 4 - len(self.username) % 4
                    if padding != 4:
                        username_padded = self.username + "=" * padding
                    else:
                        username_padded = self.username
                    decoded = base64.urlsafe_b64decode(username_padded).decode("utf-8")
                    if ":" in decoded:
                        self.username, self.password = decoded.split(":", 1)
                except:
                    pass

            query = parse_qs(url.query)

            # Security
            if "security" in query:
                self.stream.security = query["security"][0]

            # SNI
            if "sni" in query:
                self.stream.sni = query["sni"][0]

            return True
        except Exception as e:
            print(f"Error parsing SOCKS link: {e}")
            return False

    def to_share_link(self) -> str:
        """Create SOCKS share link."""
        if self.socks_version == SocksType.SOCKS4:
            scheme = "socks4"
        elif self.socks_version == SocksType.SOCKS4A:
            scheme = "socks4a"
        else:
            scheme = "socks5"

        url = f"{scheme}://"

        if self.username or self.password:
            if self.username:
                url += quote(self.username)
            if self.password:
                url += ":" + quote(self.password)
            url += "@"

        url += f"{self.server_address}:{self.server_port}"

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Построить outbound для sing-box."""
        outbound: dict[str, Any] = {
            "type": "socks",
            "server": self.server_address,
            "server_port": self.server_port,
        }

        if self.socks_version == SocksType.SOCKS4:
            outbound["version"] = "4"

        if self.name:
            outbound["tag"] = self.name

        if self.username and self.password:
            outbound["username"] = self.username
            outbound["password"] = self.password

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound


@dataclass
class HttpBean(ProxyBean):
    """HTTP proxy profile."""

    username: str = ""
    password: str = ""
    stream: StreamSettings = field(default_factory=StreamSettings)

    @property
    def proxy_type(self) -> str:
        return "http"

    def try_parse_link(self, link: str) -> bool:
        """Parse HTTP share link."""
        if not link.startswith("http://") and not link.startswith("https://"):
            return False

        try:
            url = urlparse(link)
            if not url.hostname:
                return False

            self.server_address = url.hostname
            self.server_port = url.port if url.port and url.port != -1 else 443

            self.username = url.username or ""
            self.password = url.password or ""

            if url.fragment:
                self.name = unquote(url.fragment)
            # HTTPS means TLS
            if link.startswith("https://"):
                self.stream.security = "tls"

            query = parse_qs(url.query)

            # Security
            if "security" in query:
                self.stream.security = query["security"][0]
            # SNI
            if "sni" in query:
                self.stream.sni = query["sni"][0]

            return True
        except Exception as e:
            print(f"Error parsing HTTP link: {e}")
            return False

    def to_share_link(self) -> str:
        """Create HTTP share link."""
        scheme = "https" if self.stream.security == "tls" else "http"

        url = f"{scheme}://"

        if self.username or self.password:
            if self.username:
                url += quote(self.username)
            if self.password:
                url += ":" + quote(self.password)
            url += "@"

        url += f"{self.server_address}:{self.server_port}"

        if self.name:
            url += "#" + quote(self.name)

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Check outbound."""
        outbound: dict[str, Any] = {
            "type": "http",
            "server": self.server_address,
            "server_port": self.server_port,
        }

        if self.name:
            outbound["tag"] = self.name

        if self.username and self.password:
            outbound["username"] = self.username
            outbound["password"] = self.password

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound


class SocksHttpBean:
    """Factory class."""

    TYPE_SOCKS4 = SocksType.SOCKS4
    TYPE_SOCKS4A = SocksType.SOCKS4A
    TYPE_SOCKS5 = SocksType.SOCKS5
    TYPE_HTTP = SocksType.HTTP

    def __new__(cls, socks_http_type: int = SocksType.SOCKS5) -> ProxyBean:
        if socks_http_type == SocksType.HTTP:
            return HttpBean()
        bean = SocksBean()
        bean.socks_version = socks_http_type
        return bean
