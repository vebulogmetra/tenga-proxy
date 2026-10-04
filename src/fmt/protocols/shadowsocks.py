from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from src.fmt.base import ProxyBean
from src.fmt.stream import StreamSettings

# Длина ключа 2022-blake3 в байтах. Ядро декодирует ключ при сборке конфига и на
# ключе другой длины отвергает конфиг целиком («bad key»).
KEY_LENGTH_2022 = {
    "2022-blake3-aes-128-gcm": 16,
    "2022-blake3-aes-256-gcm": 32,
    "2022-blake3-chacha20-poly1305": 32,
}

# Методы, которые принимает xray-core: AEAD и 2022-blake3. Потоковые шифры и
# none/plain ядро отвергает вместе со всем конфигом.
SUPPORTED_METHODS = frozenset(
    {
        "aes-128-gcm",
        "aes-256-gcm",
        "chacha20-poly1305",
        "chacha20-ietf-poly1305",
        "xchacha20-poly1305",
        "xchacha20-ietf-poly1305",
        *KEY_LENGTH_2022,
    }
)


def _decode_base64(data: str) -> str | None:
    """Строго декодировать base64 любого из двух алфавитов.

    Чужой символ или битый UTF-8 означают «это не base64»: нестрогий декодер
    молча выбрасывает лишние символы и возвращает мусор вместо ошибки.
    """
    padded = data.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        return base64.b64decode(padded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _is_valid_2022_key(method: str, password: str) -> bool:
    """У 2022-blake3 каждый ключ (их несколько через «:») — base64 нужной длины."""
    expected = KEY_LENGTH_2022.get(method)
    if expected is None:
        return True
    for key in password.split(":"):
        try:
            if len(base64.b64decode(key, validate=True)) != expected:
                return False
        except ValueError:
            return False
    return True


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
        """Parse Shadowsocks share link (SIP002 и legacy)."""
        if not link.lower().startswith("ss://"):
            return False

        try:
            body, _, fragment = link[5:].partition("#")
            body, _, query = body.partition("?")
            body = body.rstrip("/")

            if "@" in body:
                userinfo, _, hostport = body.rpartition("@")
                # SIP002: учётка AEAD — base64(method:password), у 2022-blake3 —
                # открытый текст с percent-кодированием. unquote, а не unquote_plus:
                # «+» — законный символ base64-ключа, пробелом он стать не должен.
                credentials = None if ":" in userinfo else _decode_base64(userinfo)
                if credentials is None or ":" not in credentials:
                    credentials = unquote(userinfo)
            else:
                # Legacy: вся ссылка — base64(method:password@host:port).
                decoded = _decode_base64(body)
                if decoded is None or "@" not in decoded:
                    return False
                credentials, _, hostport = decoded.rpartition("@")

            if ":" not in credentials:
                return False
            method, password = credentials.split(":", 1)

            # urlsplit разбирает и IPv6 в квадратных скобках.
            address = urlsplit("//" + hostport)
            if not address.hostname or not address.port:
                return False

            self.method = method.strip().lower()
            self.password = password
            self.server_address = address.hostname
            self.server_port = address.port
            self.name = unquote(fragment)
            self.plugin = parse_qs(query).get("plugin", [""])[0]

            return bool(self.password) and _is_valid_2022_key(self.method, self.password)
        except Exception:
            return False

    def to_share_link(self) -> str:
        """Create Shadowsocks share link."""
        # For 2022 methods use special format
        if self.method.startswith("2022-"):
            userinfo = f"{self.method}:{quote(self.password)}"
        else:
            # Standard format with base64
            method_password = f"{self.method}:{self.password}"
            userinfo = (
                base64.urlsafe_b64encode(method_password.encode("utf-8"))
                .decode("utf-8")
                .rstrip("=")
            )

        url = f"ss://{userinfo}@{self.server_address}:{self.server_port}"

        if self.plugin:
            url += f"?plugin={quote(self.plugin)}"

        if self.name:
            url += f"#{quote(self.name)}"

        return url

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        """Build outbound for xray-core."""
        # Неподдерживаемый метод ядро отвергает вместе со всем конфигом, а
        # SIP003-плагинов в нём нет: без плагина сервер профиля не ответит.
        if self.method.lower() not in SUPPORTED_METHODS:
            raise ValueError(f"Метод Shadowsocks «{self.method}» не поддерживается xray-core")
        if self.plugin:
            raise ValueError("Плагины Shadowsocks (SIP003) не поддерживаются xray-core")

        outbound: dict[str, Any] = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": self.server_address,
                        "port": self.server_port,
                        "method": self.method.lower(),
                        "password": self.password,
                    }
                ]
            },
        }

        if self.name:
            outbound["tag"] = self.name

        self.stream.apply_to_outbound(outbound, skip_cert)

        return outbound


ShadowSocksBean = ShadowsocksBean
