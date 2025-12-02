from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict
from urllib.parse import urlparse, parse_qs, unquote, quote

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings


@dataclass
class ShadowsocksBean(ProxyBean):
    """Shadowsocks profile."""
    
    method: str = "aes-128-gcm"
    password: str = ""
    plugin: str = ""
    uot_version: int = 0  # UDP over TCP version
    stream: StreamSettings = field(default_factory=StreamSettings)
    
    @property
    def proxy_type(self) -> str:
        return "shadowsocks"
    
    # Alias
    @property
    def uot(self) -> int:
        return self.uot_version
    
    @uot.setter
    def uot(self, value: int) -> None:
        self.uot_version = value
    
    def try_parse_link(self, link: str) -> bool:
        """Parse Shadowsocks share link."""
        if not link.startswith("ss://"):
            return False
        
        try:
            # Remove prefix
            link_body = link[5:]
            if self._try_parse_base64_format(link_body):
                return True
            return self._try_parse_url_format(link_body)
            
        except Exception as e:
            print(f"Error parsing Shadowsocks link: {e}")
            return False
    
    def _try_parse_base64_format(self, link_body: str) -> bool:
        """Parse base64 format: ss://base64#name."""
        if '@' in link_body and ':' in link_body[:20]:
            return False
        
        try:
            encoded = link_body
            if '#' in encoded:
                parts = encoded.split('#', 1)
                encoded = parts[0]
                self.name = unquote(parts[1]) if len(parts) > 1 else ""

            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += '=' * padding
            
            decoded = base64.urlsafe_b64decode(encoded).decode('utf-8', errors='ignore')
            
            # Format: method:password@server:port
            if '@' in decoded:
                method_pass, server_port = decoded.rsplit('@', 1)
                if ':' in method_pass:
                    self.method, self.password = method_pass.split(':', 1)
                if ':' in server_port:
                    self.server_address, port_str = server_port.rsplit(':', 1)
                    self.server_port = int(port_str)
                return bool(self.server_address and self.password)
            
            return False
        except:
            return False
    
    def _try_parse_url_format(self, link_body: str) -> bool:
        """Parse URL format."""
        try:
            url = urlparse("ss://" + link_body)
            
            if url.hostname:
                self.server_address = url.hostname
            if url.port:
                self.server_port = url.port
            
            # Username may contain method:password or be base64
            if url.username:
                if ':' in url.username:
                    parts = url.username.split(':', 1)
                    self.method = parts[0]
                    
                    # For 2022 methods
                    if self.method.startswith("2022-"):
                        if url.password:
                            self.password = url.password
                    else:
                        # Standard base64 password decoding
                        try:
                            password_encoded = parts[1]
                            padding = 4 - len(password_encoded) % 4
                            if padding != 4:
                                password_encoded += '=' * padding
                            self.password = base64.urlsafe_b64decode(password_encoded).decode('utf-8')
                        except:
                            self.password = parts[1]
                else:
                    # Only method, password separately
                    self.method = url.username
                    if url.password:
                        try:
                            password_encoded = url.password
                            padding = 4 - len(password_encoded) % 4
                            if padding != 4:
                                password_encoded += '=' * padding
                            self.password = base64.urlsafe_b64decode(password_encoded).decode('utf-8')
                        except:
                            self.password = url.password
            
            if url.fragment:
                self.name = unquote(url.fragment)
            
            # Plugin from query
            if url.query:
                params = parse_qs(url.query)
                if 'plugin' in params:
                    self.plugin = params['plugin'][0]
            
            return bool(self.server_address)
        except:
            return False
    
    def to_share_link(self) -> str:
        """Create Shadowsocks share link."""
        # For 2022 methods use special format
        if self.method.startswith("2022-"):
            userinfo = f"{self.method}:{quote(self.password)}"
        else:
            # Standard format with base64
            method_password = f"{self.method}:{self.password}"
            userinfo = base64.urlsafe_b64encode(
                method_password.encode('utf-8')
            ).decode('utf-8').rstrip('=')
        
        url = f"ss://{userinfo}@{self.server_address}:{self.server_port}"
        
        if self.plugin:
            url += f"?plugin={quote(self.plugin)}"
        
        if self.name:
            url += f"#{quote(self.name)}"
        
        return url
    
    def build_outbound(self, skip_cert: bool = False) -> Dict[str, Any]:
        """Build outbound for sing-box."""
        outbound: Dict[str, Any] = {
            "type": "shadowsocks",
            "server": self.server_address,
            "server_port": self.server_port,
            "method": self.method,
            "password": self.password,
        }
        
        if self.name:
            outbound["tag"] = self.name
        
        # UDP over TCP
        if self.uot_version > 0:
            outbound["udp_over_tcp"] = {
                "enabled": True,
                "version": self.uot_version
            }
        else:
            outbound["udp_over_tcp"] = False
        
        # Plugin
        if self.plugin.strip():
            plugin_parts = self.plugin.split(";", 1)
            outbound["plugin"] = plugin_parts[0]
            if len(plugin_parts) > 1:
                outbound["plugin_opts"] = plugin_parts[1]
        
        # Stream settings
        self.stream.apply_to_outbound(outbound, skip_cert)
        
        return outbound

ShadowSocksBean = ShadowsocksBean
