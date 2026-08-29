from __future__ import annotations

import base64
import string
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote

if TYPE_CHECKING:
    from src.fmt.base import ProxyBean


def looks_like_base64(data: str) -> bool:
    """Похоже ли содержимое на base64.

    Нужна отдельная проверка: `decode_base64` декодирует с errors="ignore" и
    на обычном тексте не падает, а возвращает мусор. Из-за этого список
    share-ссылок мог «декодироваться» в бессмыслицу, и подписка молча давала
    ноль профилей — срабатывало через раз, в зависимости от длины содержимого.
    """
    stripped = "".join(data.split())
    if not stripped:
        return False
    allowed = set(string.ascii_letters + string.digits + "+/=-_")
    return all(ch in allowed for ch in stripped)


def decode_base64(data: str, url_safe: bool = True) -> str | None:
    if not looks_like_base64(data):
        return None

    try:
        # Add padding
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding

        if url_safe:
            decoded = base64.urlsafe_b64decode(data)
        else:
            decoded = base64.b64decode(data)

        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        return None


def encode_base64(data: str, url_safe: bool = True) -> str:
    encoded = data.encode("utf-8")
    if url_safe:
        result = base64.urlsafe_b64encode(encoded)
    else:
        result = base64.b64encode(encoded)
    return result.decode("utf-8").rstrip("=")


def parse_url_fragment(url: str) -> tuple[str, str]:
    if "#" in url:
        parts = url.split("#", 1)
        return parts[0], unquote(parts[1])
    return url, ""


def parse_query_params(query: str) -> dict[str, str]:
    if not query:
        return {}

    params = parse_qs(query)
    return {k: v[0] for k, v in params.items() if v}


def get_query_param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    """Get first value of query parameter."""
    values = params.get(key, [])
    return values[0] if values else default


class LinkParser:
    """Base class for parsing share links."""

    SCHEMES: list[str] = []

    @classmethod
    def can_parse(cls, link: str) -> bool:
        """Check if parser can handle link."""
        link_lower = link.lower()
        return any(link_lower.startswith(scheme) for scheme in cls.SCHEMES)

    @classmethod
    def parse_security(cls, value: str, default: str = "") -> str:
        """Normalize security value."""
        value = value.lower()
        if value == "reality":
            return "tls"
        if value == "none":
            return ""
        if value in ("tls", ""):
            return value
        return default

    @classmethod
    def parse_network(cls, value: str) -> str:
        """Normalize network value."""
        value = value.lower()
        # Нормализуем для xray-core
        if value == "h2":
            return "http"
        return value

    @classmethod
    def parse_transport_params(
        cls,
        network: str,
        params: dict[str, list[str]],
    ) -> dict[str, str]:
        result = {"path": "", "host": "", "header_type": ""}

        if network in ("ws", "http", "httpupgrade"):
            result["path"] = get_query_param(params, "path")
            result["host"] = get_query_param(params, "host")
            if network == "http":
                # HTTP can use | as host separator
                result["host"] = result["host"].replace("|", ",")

        elif network == "grpc":
            result["path"] = get_query_param(params, "serviceName")

        elif network == "tcp":
            if get_query_param(params, "headerType") == "http":
                result["header_type"] = "http"
                result["path"] = get_query_param(params, "path")
                result["host"] = get_query_param(params, "host")

        return result

    @classmethod
    def parse_reality_params(cls, params: dict[str, list[str]]) -> dict[str, str]:
        """Parse Reality parameters."""
        return {
            "public_key": get_query_param(params, "pbk"),
            "short_id": get_query_param(params, "sid"),
            "spider_x": get_query_param(params, "spx"),
        }


def detect_link_type(link: str) -> str | None:
    link_lower = link.lower()

    if link_lower.startswith("vless://"):
        return "vless"
    if link_lower.startswith("trojan://"):
        return "trojan"
    if link_lower.startswith(("hysteria2://", "hy2://")):
        return "hysteria2"
    if link_lower.startswith("vmess://"):
        return "vmess"
    if link_lower.startswith("ss://"):
        return "shadowsocks"
    if link_lower.startswith(("socks://", "socks4://", "socks4a://", "socks5://")):
        return "socks"
    if link_lower.startswith(("http://", "https://")):
        return "http"
    if link_lower.startswith("tenga://"):
        return "tenga"

    return None


def parse_link(link: str) -> ProxyBean | None:
    from src.fmt.protocols import (
        HttpBean,
        Hysteria2Bean,
        ShadowsocksBean,
        SocksBean,
        TrojanBean,
        VLESSBean,
        VMessBean,
    )

    link_type = detect_link_type(link)
    if not link_type:
        return None

    bean: ProxyBean | None = None

    if link_type == "vless":
        bean = VLESSBean()
    elif link_type == "trojan":
        bean = TrojanBean()
    elif link_type == "vmess":
        bean = VMessBean()
    elif link_type == "hysteria2":
        bean = Hysteria2Bean()
    elif link_type == "shadowsocks":
        bean = ShadowsocksBean()
    elif link_type == "socks":
        bean = SocksBean()
    elif link_type == "http":
        bean = HttpBean()

    if bean and bean.try_parse_link(link):
        return bean

    return None


def parse_subscription_content(content: str) -> list[ProxyBean]:
    from src.fmt.json_config import looks_like_json, parse_json_config

    results: list[ProxyBean] = []

    # Часть провайдеров отдаёт подписку готовым xray-конфигом, а не списком
    # ссылок. Формат определяем по первому непробельному символу — ни URL, ни
    # заголовки его не выдают. Проверяем до base64: decode_base64 работает с
    # errors="ignore" и «успешно» превращает JSON в мусор.
    if looks_like_json(content):
        json_profiles = parse_json_config(content)
        if json_profiles:
            return json_profiles

    decoded = decode_base64(content.strip())
    if decoded:
        content = decoded

    if "proxies:" in content:
        # TODO: Parse Clash YAML
        pass

    # Подписка могла быть base64 от xray-конфига.
    if looks_like_json(content):
        json_profiles = parse_json_config(content)
        if json_profiles:
            return json_profiles

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        bean = parse_link(line)
        if bean:
            results.append(bean)

    return results
