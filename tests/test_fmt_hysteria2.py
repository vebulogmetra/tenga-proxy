"""hysteria2 protocol with finalmask obfuscation (port of android 984ccf5)."""

import json
from urllib.parse import quote

from src.fmt import parse_link, parse_subscription_content
from src.fmt.protocols import Hysteria2Bean

FM = '{"salamander":{"password":"secret"}}'


def make_link(**kw):
    base = kw.pop("base", "hysteria2://pass123@example.com:8443")
    query = "&".join(f"{k}={v}" for k, v in kw.items())
    return f"{base}?{query}" if query else base


def test_parses_basic_link():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass123@example.com:8443#Home") is True
    assert bean.proxy_type == "hysteria2"
    assert bean.server_address == "example.com"
    assert bean.server_port == 8443
    assert bean.auth == "pass123"
    assert bean.name == "Home"


def test_hy2_scheme_alias():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hy2://pass123@example.com:8443") is True
    assert bean.auth == "pass123"


def test_default_port_is_443():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass123@example.com") is True
    assert bean.server_port == 443


def test_always_tls_over_hysteria_transport():
    bean = Hysteria2Bean()
    bean.try_parse_link("hysteria2://pass123@example.com:8443")
    assert bean.stream.security == "tls"
    # Именно "hysteria": транспорт "udp" ядро отвергает.
    assert bean.stream.network == "hysteria"


def test_parses_tls_and_obfs_params():
    link = make_link(sni="cdn.example.com", alpn="h3", insecure="1", obfs="salamander")
    link += "&obfs-password=obfspass"
    bean = Hysteria2Bean()
    assert bean.try_parse_link(link) is True
    assert bean.stream.sni == "cdn.example.com"
    assert bean.stream.alpn == "h3"
    assert bean.stream.allow_insecure is True
    assert bean.obfs == "salamander"
    assert bean.obfs_password == "obfspass"


def test_parses_finalmask():
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(fm=quote(FM))) is True
    assert json.loads(bean.final_mask) == json.loads(FM)


def test_broken_finalmask_is_dropped_not_fatal():
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(fm=quote("{not json"))) is True
    assert bean.final_mask == ""


def test_rejects_wrong_scheme_and_missing_auth():
    assert Hysteria2Bean().try_parse_link("vless://x@example.com:443") is False
    assert Hysteria2Bean().try_parse_link("hysteria2://@example.com:8443") is False


def test_outbound_uses_flat_settings_with_version():
    """Схема сверена с `xray -test`: плоские настройки + обязательный version=2."""
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander") + "&obfs-password=obfspass")
    out = bean.build_outbound()
    assert out["protocol"] == "hysteria"
    settings = out["settings"]
    assert settings["address"] == "example.com"
    assert settings["port"] == 8443
    assert settings["auth"] == "pass123"
    # Без version ядро падает с `version != 2`.
    assert settings["version"] == 2
    assert settings["obfs"] == "salamander"
    assert settings["password"] == "obfspass"


def test_outbound_sets_hysteria_transport():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link())
    stream = bean.build_outbound()["streamSettings"]
    assert stream["network"] == "hysteria"
    assert stream["hysteriaSettings"] == {"version": 2, "auth": "pass123"}


def test_outbound_carries_finalmask():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(fm=quote(FM)))
    out = bean.build_outbound()
    assert out["streamSettings"]["finalmask"] == json.loads(FM)


def test_outbound_without_finalmask_has_no_key():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link())
    assert "finalmask" not in out_stream(bean)


def out_stream(bean):
    return bean.build_outbound().get("streamSettings", {})


def test_build_core_obj_xray_reports_no_error():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(fm=quote(FM)))
    result = bean.build_core_obj_xray()
    assert result["error"] == ""
    assert result["outbound"]["protocol"] == "hysteria"


def test_share_link_roundtrip():
    link = make_link(
        sni="cdn.example.com", alpn="h3", insecure="1", obfs="salamander", fm=quote(FM)
    )
    link += "&obfs-password=obfspass#Home"
    bean = Hysteria2Bean()
    assert bean.try_parse_link(link) is True

    restored = Hysteria2Bean()
    assert restored.try_parse_link(bean.to_share_link()) is True
    assert restored.auth == "pass123"
    assert restored.server_address == "example.com"
    assert restored.server_port == 8443
    assert restored.stream.sni == "cdn.example.com"
    assert restored.stream.alpn == "h3"
    assert restored.stream.allow_insecure is True
    assert restored.obfs == "salamander"
    assert restored.obfs_password == "obfspass"
    assert json.loads(restored.final_mask) == json.loads(FM)
    assert restored.name == "Home"


def test_parse_link_registry_returns_hysteria2():
    bean = parse_link("hysteria2://pass123@example.com:8443#Home")
    assert isinstance(bean, Hysteria2Bean)
    assert bean.auth == "pass123"

    assert isinstance(parse_link("hy2://pass123@example.com:8443"), Hysteria2Bean)


def test_subscription_parses_hysteria2_lines():
    content = "\n".join(
        [
            "hysteria2://pass123@example.com:8443#One",
            "vless://uuid-1@example.com:443?type=tcp#Two",
        ]
    )
    beans = parse_subscription_content(content)
    assert [b.proxy_type for b in beans] == ["hysteria2", "vless"]


def test_serialization_roundtrip_preserves_fields():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander", fm=quote(FM)) + "&obfs-password=obfspass")
    restored = Hysteria2Bean.from_dict(bean.to_dict())
    assert restored.auth == "pass123"
    assert restored.obfs == "salamander"
    assert restored.obfs_password == "obfspass"
    assert json.loads(restored.final_mask) == json.loads(FM)
    assert restored.stream.security == "tls"


def test_profile_entry_restores_hysteria2():
    from src.db.profiles import ProfileEntry

    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(fm=quote(FM)))
    entry = ProfileEntry(id=1, group_id=0, bean=bean)
    restored = ProfileEntry.from_dict(entry.to_dict())
    assert restored is not None
    assert isinstance(restored.bean, Hysteria2Bean)
    assert restored.bean.auth == "pass123"
    assert json.loads(restored.bean.final_mask) == json.loads(FM)
