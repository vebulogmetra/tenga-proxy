from src.fmt.stream import StreamSettings


def test_stream_settings_defaults():
    stream = StreamSettings()
    assert stream.network == "tcp"
    assert stream.path == ""
    assert stream.host == ""
    assert stream.security == ""
    assert stream.sni == ""
    assert stream.packet_encoding == "xudp"


def test_stream_settings_reality_aliases():
    stream = StreamSettings()
    stream.reality_pbk = "test_pbk"
    stream.reality_sid = "test_sid"
    stream.reality_spx = "test_spx"
    assert stream.reality_public_key == "test_pbk"
    assert stream.reality_short_id == "test_sid"
    assert stream.reality_spider_x == "test_spx"


def test_build_transport_tcp_no_http():
    stream = StreamSettings(network="tcp", header_type="")
    assert stream.build_transport() is None


def test_build_transport_websocket():
    stream = StreamSettings(network="ws", path="/path", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["type"] == "ws"
    assert transport["path"] == "/path"
    assert "Host" in transport["headers"]
    assert transport["headers"]["Host"] == "example.com"


def test_build_transport_websocket_with_early_data_in_path():
    stream = StreamSettings(network="ws", path="/path?ed=2048")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["path"] == "/path"
    assert transport["max_early_data"] == 2048
    assert transport["early_data_header_name"] == "Sec-WebSocket-Protocol"


def test_build_transport_websocket_with_early_data_property():
    stream = StreamSettings(
        network="ws", ws_early_data_length=4096, ws_early_data_name="Custom-Header"
    )
    transport = stream.build_transport()
    assert transport is not None
    assert transport["max_early_data"] == 4096
    assert transport["early_data_header_name"] == "Custom-Header"


def test_build_transport_http():
    stream = StreamSettings(network="http", path="/h2", host="example.com,example.org")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["type"] == "http"
    assert transport["path"] == "/h2"
    assert transport["host"] == ["example.com", "example.org"]


def test_build_transport_grpc():
    stream = StreamSettings(network="grpc", path="service_name")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["type"] == "grpc"
    assert transport["service_name"] == "service_name"


def test_build_transport_httpupgrade():
    stream = StreamSettings(network="httpupgrade", path="/upgrade", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["type"] == "httpupgrade"
    assert transport["path"] == "/upgrade"
    assert transport["host"] == "example.com"


def test_build_transport_tcp_with_http_header():
    stream = StreamSettings(network="tcp", header_type="http", path="/http", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["type"] == "http"
    assert transport["method"] == "GET"
    assert transport["path"] == "/http"
    assert "Host" in transport["headers"]
    assert transport["headers"]["Host"] == ["example.com"]


def test_build_tls_none():
    stream = StreamSettings(security="")
    assert stream.build_tls() is None


def test_build_tls_basic():
    stream = StreamSettings(security="tls", sni="example.com", allow_insecure=True)
    tls = stream.build_tls()
    assert tls is not None
    assert tls["enabled"] is True
    assert tls["insecure"] is True
    assert tls["server_name"] == "example.com"


def test_build_tls_with_certificate():
    stream = StreamSettings(security="tls", certificate="cert_data")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["certificate"] == "cert_data"


def test_build_tls_with_alpn():
    stream = StreamSettings(security="tls", alpn="h2,http/1.1")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["alpn"] == ["h2", "http/1.1"]


def test_build_tls_reality():
    stream = StreamSettings(
        security="reality", reality_public_key="pbk", reality_short_id="sid1,sid2"
    )
    tls = stream.build_tls()
    assert tls is not None
    assert "reality" in tls
    assert tls["reality"]["enabled"] is True
    assert tls["reality"]["public_key"] == "pbk"
    assert tls["reality"]["short_id"] == "sid1"


def test_build_tls_reality_sets_utls_random():
    stream = StreamSettings(security="reality", reality_public_key="pbk")
    tls = stream.build_tls()
    assert tls is not None
    assert "utls" in tls
    assert tls["utls"]["enabled"] is True
    assert tls["utls"]["fingerprint"] == "random"


def test_build_tls_with_utls_fingerprint():
    stream = StreamSettings(security="tls", utls_fingerprint="chrome")
    tls = stream.build_tls()
    assert tls is not None
    assert "utls" in tls
    assert tls["utls"]["fingerprint"] == "chrome"


def test_build_tls_skip_cert():
    stream = StreamSettings(security="tls", allow_insecure=False)
    tls = stream.build_tls(skip_cert=True)
    assert tls is not None
    assert tls["insecure"] is True


def test_apply_to_outbound():
    stream = StreamSettings(
        network="ws", path="/ws", security="tls", sni="example.com", packet_encoding="xudp"
    )
    outbound = {"type": "vmess"}
    stream.apply_to_outbound(outbound)
    assert "transport" in outbound
    assert outbound["transport"]["type"] == "ws"
    assert "tls" in outbound
    assert outbound["tls"]["enabled"] is True
    assert outbound["packet_encoding"] == "xudp"


def test_apply_to_outbound_vless():
    stream = StreamSettings(packet_encoding="udp")
    outbound = {"type": "vless"}
    stream.apply_to_outbound(outbound)
    assert outbound["packet_encoding"] == "udp"


def test_apply_to_outbound_non_vmess_vless():
    stream = StreamSettings(packet_encoding="xudp")
    outbound = {"type": "trojan"}
    stream.apply_to_outbound(outbound)
    assert "packet_encoding" not in outbound
