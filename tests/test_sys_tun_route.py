from src.sys.tun_route import _parse_default_route, _resolve_ipv4


def test_parse_default_route_with_gateway_and_metric():
    line = "default via 192.168.0.1 dev wlp1s0 proto dhcp src 192.168.0.154 metric 600"
    gateway, dev, metric = _parse_default_route(line)
    assert gateway == "192.168.0.1"
    assert dev == "wlp1s0"
    assert metric == "600"


def test_parse_default_route_without_gateway():
    line = "default dev xray0 scope link"
    gateway, dev, metric = _parse_default_route(line)
    assert gateway is None
    assert dev == "xray0"
    assert metric is None


def test_resolve_ipv4_accepts_valid_literal():
    assert _resolve_ipv4("8.8.8.8") == "8.8.8.8"


def test_resolve_ipv4_rejects_invalid_literal():
    assert _resolve_ipv4("999.999.999.999") is None
