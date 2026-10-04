"""hysteria2 protocol with finalmask obfuscation (port of android 984ccf5)."""

import json
from urllib.parse import quote

import pytest

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
    """Схема сверена с исходником форка (infra/conf/hysteria.go).

    HysteriaClientConfig = {Version, Address, Port} и ничего больше: auth живёт
    в транспорте, а obfs/password/congestion/up/down в клиентском конфиге
    отсутствуют вовсе. Лишние ключи ядро молча игнорирует.
    """
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander") + "&obfs-password=obfspass")
    out = bean.build_outbound()
    assert out["protocol"] == "hysteria"
    settings = out["settings"]
    assert settings["address"] == "example.com"
    assert settings["port"] == 8443
    # Без version ядро падает с `version != 2`.
    assert settings["version"] == 2
    # auth — только в транспорте: в settings это поле HysteriaServerConfig.
    assert "auth" not in settings
    # obfs/password не существуют в клиентском конфиге — обфускация только finalmask.
    assert "obfs" not in settings
    assert "password" not in settings


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


def test_obfs_becomes_salamander_udp_mask():
    """obfs из ссылки превращается в udp-маску finalmask.

    В клиентском конфиге форка нет полей obfs/password — единственный рабочий
    путь для salamander это `finalmask.udp[{type,settings}]`. Плоская форма
    `{"salamander": {...}}` ядром молча игнорируется.
    """
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander") + "&obfs-password=obfspass")
    stream = bean.build_outbound()["streamSettings"]

    assert stream["finalmask"] == {
        "udp": [{"type": "salamander", "settings": {"password": "obfspass"}}]
    }


def test_obfs_without_password_still_builds_mask():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander"))
    stream = bean.build_outbound()["streamSettings"]
    assert stream["finalmask"]["udp"][0]["type"] == "salamander"
    assert stream["finalmask"]["udp"][0]["settings"] == {"password": ""}


def test_unknown_obfs_type_is_ignored():
    """Неизвестный obfs не превращаем в маску: ядро отвергло бы весь конфиг."""
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="somethingelse") + "&obfs-password=x")
    stream = bean.build_outbound()["streamSettings"]
    assert "finalmask" not in stream


FM_UDP = '{"udp":[{"type":"salamander","settings":{"password":"from-fm"}}]}'


def test_mask_type_from_fm_is_not_duplicated():
    """Явный ?fm= авторитетнее: тип, который в нём уже есть, из obfs не добавляется."""
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander", fm=quote(FM_UDP)) + "&obfs-password=obfspass")
    stream = bean.build_outbound()["streamSettings"]
    assert stream["finalmask"] == json.loads(FM_UDP)


def test_obfs_is_added_when_fm_lacks_it():
    """fm без salamander не отменяет obfs из ссылки: иначе профиль остаётся без обфускации."""
    fm = '{"quicParams":{"congestion":"bbr"}}'
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(obfs="salamander", fm=quote(fm)) + "&obfs-password=obfspass")
    stream = bean.build_outbound()["streamSettings"]
    assert stream["finalmask"] == {
        "quicParams": {"congestion": "bbr"},
        "udp": [{"type": "salamander", "settings": {"password": "obfspass"}}],
    }


# --- port hopping и brutal ---


def test_multi_port_authority_is_parsed():
    """Официальный формат: host:443,20000-50000 — первый порт основной."""
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass123@example.com:443,20000-50000/?sni=a.com#Hop")

    assert bean.server_address == "example.com"
    assert bean.server_port == 443
    assert bean.hop_ports == "443,20000-50000"
    assert bean.auth == "pass123"
    assert bean.name == "Hop"


def test_port_range_only_authority():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass123@example.com:20000-50000")
    assert bean.server_port == 20000
    assert bean.hop_ports == "20000-50000"


def test_multi_port_authority_with_ipv6_host():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass123@[2001:db8::1]:443,5000-6000")
    assert bean.server_address == "2001:db8::1"
    assert bean.server_port == 443
    assert bean.hop_ports == "443,5000-6000"


def test_mport_param_sets_hop_ports():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000"))
    assert bean.server_port == 8443
    assert bean.hop_ports == "20000-50000"


def test_invalid_port_spec_is_dropped():
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(mport="50000-20000"))
    assert bean.hop_ports == ""
    assert bean.try_parse_link(make_link(mport="0-70000"))
    assert bean.hop_ports == ""


def test_hop_interval_is_parsed_and_validated():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000") + "&hop-interval=20-40")
    assert bean.hop_interval == "20-40"

    # Меньше 5 секунд ядро отвергает при dial — отбрасываем заранее.
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000", hopInterval="3"))
    assert bean.hop_interval == ""


def test_bandwidth_params_are_parsed():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(upmbps="50", downmbps="100"))
    assert (bean.up_mbps, bean.down_mbps) == (50, 100)

    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(upmbps="fast", downmbps="-1"))
    assert (bean.up_mbps, bean.down_mbps) == (0, 0)


def test_hop_ports_become_first_udp_mask():
    """udphop обязан быть первым в finalmask.udp, salamander — после него."""
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000", obfs="salamander") + "&obfs-password=p")
    udp = bean.build_outbound()["streamSettings"]["finalmask"]["udp"]

    assert udp == [
        {
            "type": "udphop",
            "settings": {
                "mode": "intervalLocal,intervalRemote",
                "interval": "30",
                "remotePorts": "20000-50000",
            },
        },
        {"type": "salamander", "settings": {"password": "p"}},
    ]


def test_hop_goes_before_masks_from_fm():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000", fm=quote(FM_UDP)) + "&hop-interval=10")
    udp = bean.build_outbound()["streamSettings"]["finalmask"]["udp"]

    assert [m["type"] for m in udp] == ["udphop", "salamander"]
    assert udp[0]["settings"]["interval"] == "10"


def test_bandwidth_becomes_brutal_quic_params():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(upmbps="50", downmbps="100"))
    mask = bean.build_outbound()["streamSettings"]["finalmask"]
    assert mask == {
        "quicParams": {"congestion": "brutal", "brutalUp": "50 mbps", "brutalDown": "100 mbps"}
    }


def test_brutal_needs_upload_rate():
    """Без upmbps brutal не включаем: скорость отдачи ему обязательна."""
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(downmbps="100"))
    assert "finalmask" not in bean.build_outbound()["streamSettings"]


def test_quic_params_from_fm_are_not_overwritten():
    fm = '{"quicParams":{"congestion":"bbr"}}'
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(upmbps="50", fm=quote(fm)))
    quic = bean.build_outbound()["streamSettings"]["finalmask"]["quicParams"]
    assert quic == {"congestion": "bbr", "brutalUp": "50 mbps"}


def test_hop_and_bandwidth_survive_share_link_roundtrip():
    bean = Hysteria2Bean()
    bean.try_parse_link(
        "hysteria2://pass123@example.com:443,20000-50000/?hop-interval=20-40&upmbps=50&downmbps=100#H"
    )
    restored = Hysteria2Bean()
    assert restored.try_parse_link(bean.to_share_link())

    assert restored.server_port == 443
    assert restored.hop_ports == "443,20000-50000"
    assert restored.hop_interval == "20-40"
    assert (restored.up_mbps, restored.down_mbps) == (50, 100)


def test_hop_fields_survive_serialization():
    bean = Hysteria2Bean()
    bean.try_parse_link(make_link(mport="20000-50000", upmbps="50"))
    restored = Hysteria2Bean.from_dict(bean.to_dict())
    assert restored.hop_ports == "20000-50000"
    assert restored.up_mbps == 50


@pytest.mark.parametrize("mport", ["", "20000-50000"])
def test_existing_udphop_is_outermost_and_keeps_provider_settings(mport):
    hop = {"type": "udphop", "settings": {"remotePorts": "9000-9010", "interval": "10"}}
    salamander = {"type": "salamander", "settings": {"password": "from-fm"}}
    fm = json.dumps({"udp": [salamander, hop]})
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(fm=quote(fm), mport=mport))
    assert bean.build_outbound()["streamSettings"]["finalmask"]["udp"] == [hop, salamander]


def test_ipv6_hopping_share_link_roundtrip():
    bean = Hysteria2Bean()
    assert bean.try_parse_link("hysteria2://pass@[2001:db8::1]:443,5000-6000")
    restored = Hysteria2Bean()
    assert restored.try_parse_link(bean.to_share_link())
    assert restored.server_address == bean.server_address
    assert restored.hop_ports == bean.hop_ports


@pytest.mark.parametrize(("key", "value"), [("hop-interval", "5%0A"), ("mport", "5000-6000%0A")])
def test_hopping_parameters_with_trailing_newline_are_rejected(key, value):
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(**{key: value}))
    assert bean.hop_interval == ""
    assert bean.hop_ports == ""


@pytest.mark.parametrize("value", ["%C2%B2", "%D9%A5"])
def test_non_ascii_bandwidth_is_ignored_without_rejecting_profile(value):
    bean = Hysteria2Bean()
    assert bean.try_parse_link(make_link(upmbps=value, downmbps=value))
    assert (bean.up_mbps, bean.down_mbps) == (0, 0)
