from src.fmt.base import ProxyBean, ProxyBeanWithStream, format_address, is_ip_address
from src.fmt.parsers import (
    decode_base64,
    detect_link_type,
    encode_base64,
    parse_link,
    parse_subscription_content,
)
from src.fmt.protocols import (
    HttpBean,
    Hysteria2Bean,
    ShadowSocksBean,  # Alias
    ShadowsocksBean,
    SocksBean,
    SocksHttpBean,
    TrojanBean,
    TrojanVLESSBean,
    VLESSBean,
    VMessBean,
)
from src.fmt.stream import StreamSettings, V2RayStreamSettings, parse_json_object

AbstractBean = ProxyBean

__all__ = [
    "AbstractBean",
    "HttpBean",
    "Hysteria2Bean",
    "ProxyBean",
    "ProxyBeanWithStream",
    "ShadowSocksBean",
    "ShadowsocksBean",
    "SocksBean",
    "SocksHttpBean",
    "StreamSettings",
    "TrojanBean",
    "TrojanVLESSBean",
    "V2RayStreamSettings",
    "VLESSBean",
    "VMessBean",
    "decode_base64",
    "detect_link_type",
    "encode_base64",
    "format_address",
    "is_ip_address",
    "parse_json_object",
    "parse_link",
    "parse_subscription_content",
]
