"""Разбор подписок, отданных готовым xray-конфигом.

Часть провайдеров отдаёт подписку не списком share-ссылок, а JSON-конфигом
xray (или массивом конфигов). Здесь outbound'ы разворачиваются обратно в
share-ссылки и разбираются штатными парсерами — так не приходится дублировать
логику протоколов и транспортов.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

if TYPE_CHECKING:
    from src.fmt.base import ProxyBean

# Служебные outbound'ы (freedom/blackhole/dns) профилями не являются.
SUPPORTED_PROTOCOLS = frozenset(
    {"vless", "trojan", "vmess", "shadowsocks", "http", "socks", "hysteria"}
)


def looks_like_json(content: str) -> bool:
    """Похоже ли содержимое на JSON.

    Определяем по первому непробельному символу: это единственный надёжный
    признак — ни URL, ни заголовки формат не выдают.
    """
    stripped = content.lstrip()
    return stripped.startswith(("{", "["))


def parse_json_config(content: str) -> list[ProxyBean]:
    """Разобрать xray-конфиг (или массив конфигов) в список профилей.

    Возвращает пустой список, если это не разобралось как пригодный конфиг —
    вызывающий тогда продолжает построчным разбором share-ссылок.
    """
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []

    if isinstance(data, list):
        # Массив может быть как списком полных конфигов, так и голым списком
        # outbound'ов — различаем по наличию ключа "outbounds".
        if any(isinstance(item, dict) and "outbounds" not in item for item in data):
            outbounds = [item for item in data if isinstance(item, dict)]
            if outbounds:
                return _parse_single({"outbounds": outbounds})

        profiles: list[ProxyBean] = []
        for item in data:
            # Битый конфиг не должен ронять всю подписку — берём что разобралось.
            if isinstance(item, dict):
                profiles.extend(_parse_single(item))
            elif isinstance(item, str):
                # Массив может быть и обычным списком ссылок.
                from src.fmt.parsers import parse_link

                bean = parse_link(item.strip())
                if bean:
                    profiles.append(bean)
        return profiles

    if isinstance(data, dict):
        return _parse_single(data)

    return []


def _parse_single(root: dict[str, Any]) -> list[ProxyBean]:
    """Разобрать один xray-конфиг."""
    from src.fmt.parsers import parse_link

    outbounds = root.get("outbounds")
    if not isinstance(outbounds, list):
        return []

    remarks = str(root.get("remarks", "")).strip()

    # Кандидаты собираем заранее: номер в имени нужен, только если узлов
    # несколько, иначе профиль называется просто тегом.
    candidates: list[tuple[dict[str, Any], str, str]] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue

        protocol = outbound.get("protocol", "")
        if protocol not in SUPPORTED_PROTOCOLS:
            continue

        candidates.append((outbound, protocol, remarks or str(outbound.get("tag", "proxy"))))

    profiles: list[ProxyBean] = []
    numbered = len(candidates) > 1
    for index, (outbound, protocol, name_base) in enumerate(candidates, start=1):
        name = f"{index}-{name_base}" if numbered else name_base

        link = _build_share_link(outbound, protocol, name)
        if not link:
            continue

        bean = parse_link(link)
        if bean is None:
            continue

        bean.name = name
        profiles.append(bean)

    return profiles


def _build_share_link(outbound: dict[str, Any], protocol: str, name: str) -> str | None:
    """Собрать share-ссылку из outbound'а."""
    builders = {
        "vless": _build_vless,
        "trojan": _build_trojan,
        "vmess": _build_vmess,
        "shadowsocks": _build_shadowsocks,
        "http": _build_http,
        "socks": _build_socks,
        "hysteria": _build_hysteria2,
    }
    builder = builders.get(protocol)
    if builder is None:
        return None
    try:
        return builder(outbound, name)
    except Exception:
        # Кривой outbound пропускаем, а не роняем разбор всей подписки.
        return None


def _first(container: Any, key: str) -> dict[str, Any] | None:
    """Первый элемент массива `key` внутри `container`."""
    if not isinstance(container, dict):
        return None
    items = container.get(key)
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return None


def _with_query(base: str, params: dict[str, str], name: str) -> str:
    url = base
    if params:
        url += "?" + urlencode(params)
    if name:
        url += "#" + quote(name)
    return url


def _build_vless(outbound: dict[str, Any], name: str) -> str | None:
    server = _first(outbound.get("settings"), "vnext")
    user = _first(server, "users") if server else None
    if not server or not user:
        return None

    address = server.get("address", "")
    port = server.get("port", 0)
    uuid = user.get("id", "")
    if not address or not port or not uuid:
        return None

    params = _stream_params(outbound)
    flow = user.get("flow", "")
    if flow:
        params["flow"] = flow

    return _with_query(f"vless://{uuid}@{address}:{port}", params, name)


def _build_trojan(outbound: dict[str, Any], name: str) -> str | None:
    server = _first(outbound.get("settings"), "servers")
    if not server:
        return None

    address = server.get("address", "")
    port = server.get("port", 0)
    password = server.get("password", "")
    if not address or not port or not password:
        return None

    params = _stream_params(outbound)
    return _with_query(f"trojan://{quote(str(password), safe='')}@{address}:{port}", params, name)


def _build_vmess(outbound: dict[str, Any], name: str) -> str | None:
    server = _first(outbound.get("settings"), "vnext")
    user = _first(server, "users") if server else None
    if not server or not user:
        return None

    address = server.get("address", "")
    port = server.get("port", 0)
    uuid = user.get("id", "")
    if not address or not port or not uuid:
        return None

    stream = outbound.get("streamSettings") or {}
    params = _stream_params(outbound)

    # vmess:// — это base64 от JSON, а не query-строка.
    payload = {
        "v": "2",
        "ps": name,
        "add": address,
        "port": str(port),
        "id": uuid,
        "aid": str(user.get("alterId", 0)),
        "scy": user.get("security", "auto"),
        "net": stream.get("network", "tcp"),
        "type": params.get("headerType", "none"),
        "host": params.get("host", ""),
        "path": params.get("path", ""),
        "tls": stream.get("security", ""),
        "sni": params.get("sni", ""),
    }
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode(
        "utf-8"
    )
    return f"vmess://{encoded}"


def _build_shadowsocks(outbound: dict[str, Any], name: str) -> str | None:
    server = _first(outbound.get("settings"), "servers")
    if not server:
        return None

    address = server.get("address", "")
    port = server.get("port", 0)
    password = server.get("password", "")
    method = server.get("method", "")
    if not address or not port or not password or not method:
        return None

    user_info = (
        base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode("utf-8").rstrip("=")
    )
    return _with_query(f"ss://{user_info}@{address}:{port}", {}, name)


def _build_credentials_link(outbound: dict[str, Any], name: str, scheme: str) -> str | None:
    """Общая сборка для http:// и socks:// — оба хранят user/pass одинаково."""
    server = _first(outbound.get("settings"), "servers")
    if not server:
        return None

    address = server.get("address", "")
    port = server.get("port", 0)
    if not address or not port:
        return None

    user_obj = _first(server, "users")
    credentials = ""
    if user_obj:
        user = user_obj.get("user", "")
        password = user_obj.get("pass", "")
        if user:
            # Percent-encoding обязателен: спецсимволы (':' '@' '/' '#') иначе
            # ломают разбор URL вплоть до подмены host.
            credentials = f"{quote(str(user), safe='')}:{quote(str(password), safe='')}@"

    return _with_query(f"{scheme}://{credentials}{address}:{port}", {}, name)


def _build_http(outbound: dict[str, Any], name: str) -> str | None:
    return _build_credentials_link(outbound, name, "http")


def _build_socks(outbound: dict[str, Any], name: str) -> str | None:
    return _build_credentials_link(outbound, name, "socks")


def _build_hysteria2(outbound: dict[str, Any], name: str) -> str | None:
    """Собрать hysteria2-ссылку.

    Схема клиентского конфига форка: `settings` плоские (version/address/port),
    а `auth` лежит в `streamSettings.hysteriaSettings`.
    """
    settings = outbound.get("settings") or {}
    stream = outbound.get("streamSettings") or {}
    hysteria_settings = stream.get("hysteriaSettings") or {}

    address = settings.get("address", "")
    port = settings.get("port", 0)
    auth = hysteria_settings.get("auth", "")
    if not address or not port or not auth:
        return None

    params: dict[str, str] = {}
    tls = stream.get("tlsSettings") or {}
    sni = tls.get("serverName", "")
    if sni:
        params["sni"] = sni
    if tls.get("allowInsecure"):
        params["insecure"] = "1"
    alpn = _alpn_to_str(tls.get("alpn"))
    if alpn:
        params["alpn"] = alpn

    final_mask = stream.get("finalmask")
    if isinstance(final_mask, dict) and final_mask:
        params["fm"] = json.dumps(final_mask, separators=(",", ":"))

    return _with_query(f"hysteria2://{quote(str(auth), safe='')}@{address}:{port}", params, name)


def _alpn_to_str(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(x) for x in value if x)
    if isinstance(value, str):
        return value
    return ""


def _stream_params(outbound: dict[str, Any]) -> dict[str, str]:
    """Развернуть streamSettings обратно в параметры share-ссылки."""
    params: dict[str, str] = {}
    stream = outbound.get("streamSettings")
    if not isinstance(stream, dict):
        return params

    network = stream.get("network", "tcp")
    # xray пишет транспорт как splithttp, в ссылках он называется xhttp.
    params["type"] = "xhttp" if network == "splithttp" else network

    security = stream.get("security", "")
    if security and security != "none":
        params["security"] = security

    tls = stream.get("realitySettings") if security == "reality" else None
    if not isinstance(tls, dict):
        tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        _tls_params(tls, params)

    _transport_params(stream, network, params)
    return params


def _tls_params(tls: dict[str, Any], params: dict[str, str]) -> None:
    sni = tls.get("serverName", "")
    if sni:
        params["sni"] = sni
    fingerprint = tls.get("fingerprint", "")
    if fingerprint:
        params["fp"] = fingerprint
    alpn = _alpn_to_str(tls.get("alpn"))
    if alpn:
        params["alpn"] = alpn
    if tls.get("allowInsecure"):
        params["allowInsecure"] = "1"
    for json_key, param in (("publicKey", "pbk"), ("shortId", "sid"), ("spiderX", "spx")):
        value = tls.get(json_key, "")
        if value:
            params[param] = value


def _transport_params(stream: dict[str, Any], network: str, params: dict[str, str]) -> None:
    if network == "ws":
        ws = stream.get("wsSettings") or {}
        if ws.get("path"):
            params["path"] = ws["path"]
        headers = ws.get("headers") or {}
        if headers.get("Host"):
            params["host"] = headers["Host"]

    elif network == "grpc":
        grpc = stream.get("grpcSettings") or {}
        if grpc.get("serviceName"):
            params["serviceName"] = grpc["serviceName"]

    elif network in ("http", "h2"):
        params["type"] = "http"
        http_settings = stream.get("httpSettings") or {}
        if http_settings.get("path"):
            params["path"] = http_settings["path"]
        host = http_settings.get("host")
        if isinstance(host, list) and host:
            params["host"] = ",".join(str(h) for h in host)
        elif isinstance(host, str) and host:
            params["host"] = host

    elif network == "httpupgrade":
        hu = stream.get("httpupgradeSettings") or {}
        if hu.get("path"):
            params["path"] = hu["path"]
        if hu.get("host"):
            params["host"] = hu["host"]

    elif network in ("splithttp", "xhttp"):
        xh = stream.get("splithttpSettings") or stream.get("xhttpSettings") or {}
        if xh.get("path"):
            params["path"] = xh["path"]
        if xh.get("host"):
            params["host"] = xh["host"]
        if xh.get("mode"):
            params["mode"] = xh["mode"]
        if xh.get("xPaddingBytes"):
            params["xPaddingBytes"] = xh["xPaddingBytes"]
        # Остальные ключи — обфускация; сохраняем целиком, иначе профиль не работает.
        extra = {k: v for k, v in xh.items() if k not in ("path", "host", "mode", "xPaddingBytes")}
        if extra:
            params["extra"] = json.dumps(extra, separators=(",", ":"))

    elif network == "tcp":
        tcp = stream.get("tcpSettings") or {}
        header = tcp.get("header") or {}
        if header.get("type") == "http":
            params["headerType"] = "http"
            request = header.get("request") or {}
            path = request.get("path")
            if isinstance(path, list) and path:
                params["path"] = str(path[0])
            elif isinstance(path, str) and path:
                params["path"] = path
            host = (request.get("headers") or {}).get("Host")
            if isinstance(host, list) and host:
                params["host"] = ",".join(str(h) for h in host)
            elif isinstance(host, str) and host:
                params["host"] = host
