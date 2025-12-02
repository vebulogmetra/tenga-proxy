from src.fmt.base import ProxyBean, ProxyBeanWithStream, is_ip_address, format_address
from src.fmt.stream import StreamSettings, V2RayStreamSettings
from src.fmt.parsers import (
    parse_link,
    parse_subscription_content,
    detect_link_type,
    decode_base64,
    encode_base64,
)

from src.fmt.protocols import (
    TrojanBean,
    VLESSBean,
    TrojanVLESSBean,
    VMessBean,
    ShadowsocksBean,
    ShadowSocksBean,  # Alias
    SocksBean,
    HttpBean,
    SocksHttpBean,
)
AbstractBean = ProxyBean

__all__ = [
    'ProxyBean',
    'ProxyBeanWithStream',
    'AbstractBean',
    'StreamSettings',
    'V2RayStreamSettings',

    'is_ip_address',
    'format_address',

    'parse_link',
    'parse_subscription_content',
    'detect_link_type',
    'decode_base64',
    'encode_base64',

    'TrojanBean',
    'VLESSBean',
    'TrojanVLESSBean',
    'VMessBean',
    'ShadowsocksBean',
    'ShadowSocksBean',
    'SocksBean',
    'HttpBean',
    'SocksHttpBean',
]
