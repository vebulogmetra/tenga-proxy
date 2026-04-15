from src.db.config import ProxyMode


def test_build_inbounds_system_proxy_mode():
    from src.core.proxy_mode import build_inbounds_for_mode

    inbounds = build_inbounds_for_mode(
        mode=ProxyMode.SYSTEM_PROXY,
        address="127.0.0.1",
        socks_port=2080,
        tun_name="tun0",
        tun_mtu=1500,
    )

    assert len(inbounds) == 2
    assert inbounds[0]["protocol"] == "socks"
    assert inbounds[0]["port"] == 2080
    assert inbounds[1]["protocol"] == "http"
    assert inbounds[1]["port"] == 2081


def test_build_inbounds_tun_mode():
    from src.core.proxy_mode import build_inbounds_for_mode

    inbounds = build_inbounds_for_mode(
        mode=ProxyMode.TUN,
        address="127.0.0.1",
        socks_port=2080,
        tun_name="xray0",
        tun_mtu=1400,
    )

    assert len(inbounds) == 1
    assert inbounds[0]["protocol"] == "tun"
    assert inbounds[0]["port"] == 0
    assert inbounds[0]["settings"]["name"] == "xray0"
    assert inbounds[0]["settings"]["MTU"] == 1400
    assert inbounds[0]["settings"]["autoRoute"] is True
    assert inbounds[0]["settings"]["strictRoute"] is True


def test_invalid_proxy_mode_fallbacks_to_tun():
    from src.core.proxy_mode import build_inbounds_for_mode, normalize_proxy_mode

    assert normalize_proxy_mode("invalid") == ProxyMode.TUN

    inbounds = build_inbounds_for_mode(
        mode="invalid",
        address="127.0.0.1",
        socks_port=2080,
        tun_name="tun0",
        tun_mtu=1500,
    )

    assert len(inbounds) == 1
    assert inbounds[0]["protocol"] == "tun"
