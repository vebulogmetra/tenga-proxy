"""Allowlisted share-link options for xray 26.9.9.

Destination-changing download streams, realm, xdns and xicmp are deliberately
excluded. A share link cannot override the profile's destination/socket policy.
Schemas follow infra/conf/transport_{method,finalmask}.go at tag v26.9.9.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_RANGE = re.compile(r"\d+(?:-\d+)?\Z")


def _filter(source: Any, schema: dict, depth: int = 0) -> dict:
    if depth > 8:
        raise ValueError("Слишком большая вложенность параметров транспорта")
    if not isinstance(source, dict):
        raise ValueError("Параметры транспорта должны быть JSON-объектом")
    result = {}
    for key, value in source.items():
        rule = schema.get(key)
        if rule is None:
            # Do not print arbitrary attacker-controlled field names or values.
            logger.warning("Отброшено поле транспорта: %s", re.sub(r"[^a-zA-Z0-9_]", "?", key)[:64])
            continue
        if isinstance(rule, list):
            if not isinstance(value, list):
                raise ValueError(f"Неверный тип параметра транспорта: {key}")
            result[key] = [
                _filter({"item": item}, {"item": rule[0]}, depth + 1)["item"] for item in value
            ]
            continue
        if isinstance(rule, dict):
            result[key] = _filter(value, rule, depth + 1)
            continue
        if rule == "range":
            valid = (type(value) is int and 0 <= value <= 2147483647) or (
                isinstance(value, str)
                and _RANGE.fullmatch(value)
                and all(int(n) <= 2147483647 for n in value.split("-"))
                and ("-" not in value or int(value.split("-")[0]) <= int(value.split("-")[1]))
            )
        elif rule == "headers":
            valid = isinstance(value, dict) and all(
                isinstance(k, str)
                and isinstance(v, str)
                and "\r" not in k + v
                and "\n" not in k + v
                and k.lower() != "host"
                for k, v in value.items()
            )
        elif rule == "strings":
            valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
        elif rule == "ranges":
            valid = isinstance(value, list)
            if valid:
                value = [_filter({"item": v}, {"item": "range"}, depth + 1)["item"] for v in value]
        elif rule == "bytes":
            valid = isinstance(value, str) or (
                isinstance(value, list) and all(type(v) is int and 0 <= v <= 255 for v in value)
            )
        elif rule == "bandwidth":
            valid = type(value) is int or isinstance(value, str)
        else:
            valid = type(value) is rule
        if not valid:
            raise ValueError(f"Неверный тип параметра транспорта: {key}")
        result[key] = value
    return result


_XMUX = dict.fromkeys(
    ("maxConcurrency", "maxConnections", "cMaxReuseTimes", "hMaxRequestTimes", "hMaxReusableSecs"),
    "range",
) | {"hKeepAlivePeriod": int}
_XHTTP = dict.fromkeys(
    (
        "host",
        "path",
        "mode",
        "xPaddingKey",
        "xPaddingHeader",
        "xPaddingPlacement",
        "xPaddingMethod",
        "uplinkHTTPMethod",
        "sessionIDPlacement",
        "sessionIDKey",
        "sessionIDTable",
        "seqPlacement",
        "seqKey",
        "uplinkDataPlacement",
        "uplinkDataKey",
    ),
    str,
)
_XHTTP.update(
    dict.fromkeys(
        (
            "xPaddingBytes",
            "sessionIDLength",
            "uplinkChunkSize",
            "scMaxEachPostBytes",
            "scMinPostsIntervalMs",
            "scStreamUpServerSecs",
        ),
        "range",
    )
)
_XHTTP.update(dict.fromkeys(("xPaddingObfsMode", "noGRPCHeader", "noSSEHeader"), bool))
_XHTTP.update(
    {"scMaxBufferedPosts": int, "serverMaxHeaderBytes": int, "headers": "headers", "xmux": _XMUX}
)
_XHTTP["extra"] = _XHTTP

_QUIC = dict.fromkeys(("congestion", "bbrProfile"), str)
_QUIC.update(dict.fromkeys(("brutalUp", "brutalDown"), "bandwidth"))
_QUIC.update(
    dict.fromkeys(
        (
            "debug",
            "brutalDisableLossCompensation",
            "disablePathMTUDiscovery",
            "disableChromeParrot",
            "disableGSO",
            "disableStatelessReset",
        ),
        bool,
    )
)
_QUIC.update(
    dict.fromkeys(
        (
            "initStreamReceiveWindow",
            "maxStreamReceiveWindow",
            "initConnectionReceiveWindow",
            "maxConnectionReceiveWindow",
            "maxIdleTimeout",
            "keepAlivePeriod",
            "maxIncomingStreams",
        ),
        int,
    )
)
_SUDOKU = {
    "password": str,
    "ascii": str,
    "customTable": str,
    "custom_table": str,
    "customTables": "strings",
    "custom_tables": "strings",
    "paddingMin": int,
    "padding_min": int,
    "paddingMax": int,
    "padding_max": int,
}
_MASKS = {
    "salamander": {"password": str, "packetSize": "range"},
    "udphop": {"mode": str, "interval": "range", "remotePorts": "bandwidth"},
    "mkcp-legacy": {"header": str, "value": str},
    "sudoku": _SUDOKU,
    "fragment": {
        "packets": str,
        "length": "range",
        "delay": "range",
        "lengths": "ranges",
        "delays": "ranges",
        "maxSplit": "range",
    },
}


# Custom headers and noise contain byte data, never arbitrary stream settings.
_TRANSFORM = {"op": str}
_ARG = {
    "type": str,
    "bytes": "bytes",
    "u64": int,
    "reuse": str,
    "metadata": str,
    "transform": _TRANSFORM,
}
_TRANSFORM["args"] = [_ARG]
_ITEM = {
    "rand": int,
    "randRange": "range",
    "capture": str,
    "type": str,
    "reuse": str,
    "transform": _TRANSFORM,
    "packet": "bytes",
}
_MASKS["header-custom-udp"] = {"mode": str, "client": [_ITEM], "server": [_ITEM]}
_MASKS["header-custom-tcp"] = {
    key: [[_ITEM | {"delay": "range"}]] for key in ("clients", "servers", "errors")
}
_MASKS["noise"] = {
    "reset": "range",
    "noise": [
        {"rand": "range", "randRange": "range", "type": str, "packet": "bytes", "delay": "range"}
    ],
}
_MASKS["xmc"] = {
    "hostname": str,
    "password": str,
    "profiles": [{"username": str, "uuid": str, "texturesValue": str, "texturesSignature": str}],
}


def filter_xhttp_options(source: dict[str, Any]) -> dict[str, Any]:
    return _filter(source, _XHTTP)


def filter_finalmask_options(source: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in source:
        if key not in ("udp", "tcp", "quicParams"):
            logger.warning("Отброшено неизвестное поле finalmask")
    if "quicParams" in source:
        result["quicParams"] = _filter(source["quicParams"], _QUIC)
    for protocol in ("tcp", "udp"):
        if protocol not in source:
            continue
        if not isinstance(source[protocol], list):
            raise ValueError(f"Параметр finalmask {protocol} должен быть списком")
        masks = []
        for mask in source[protocol]:
            if not isinstance(mask, dict):
                raise ValueError("Маска должна быть JSON-объектом")
            kind = mask.get("type")
            allowed = (
                ("fragment", "sudoku", "header-custom", "xmc")
                if protocol == "tcp"
                else ("salamander", "udphop", "sudoku", "mkcp-legacy", "noise", "header-custom")
            )
            if kind not in allowed:
                logger.warning("Отброшен неподдерживаемый тип finalmask")
                continue
            masks.append(
                {
                    "type": kind,
                    "settings": _filter(
                        mask.get("settings", {}),
                        _MASKS[f"header-custom-{protocol}" if kind == "header-custom" else kind],
                    ),
                }
            )
        if masks:
            result[protocol] = masks
    return result
