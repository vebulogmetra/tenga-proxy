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
    """Test WebSocket transport for xray-core format."""
    stream = StreamSettings(network="ws", path="/path", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["network"] == "ws"
    assert "wsSettings" in transport
    assert transport["wsSettings"]["path"] == "/path"
    assert transport["wsSettings"]["headers"]["Host"] == "example.com"


def test_build_transport_websocket_with_early_data_in_path():
    """Test WebSocket early data parsed from path for xray-core."""
    stream = StreamSettings(network="ws", path="/path?ed=2048")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["wsSettings"]["path"] == "/path"
    assert transport["wsSettings"]["maxEarlyData"] == 2048
    assert transport["wsSettings"]["earlyDataHeaderName"] == "Sec-WebSocket-Protocol"


def test_build_transport_websocket_with_early_data_property():
    """Test WebSocket early data via property for xray-core."""
    stream = StreamSettings(
        network="ws", ws_early_data_length=4096, ws_early_data_name="Custom-Header"
    )
    transport = stream.build_transport()
    assert transport is not None
    assert transport["wsSettings"]["maxEarlyData"] == 4096
    assert transport["wsSettings"]["earlyDataHeaderName"] == "Custom-Header"


def test_build_transport_http():
    """Test HTTP/2 transport for xray-core format."""
    stream = StreamSettings(network="http", path="/h2", host="example.com,example.org")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["network"] == "http"
    assert "httpSettings" in transport
    assert transport["httpSettings"]["path"] == "/h2"
    assert transport["httpSettings"]["host"] == ["example.com", "example.org"]


def test_build_transport_grpc():
    """Test gRPC transport for xray-core format."""
    stream = StreamSettings(network="grpc", path="service_name")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["network"] == "grpc"
    assert "grpcSettings" in transport
    assert transport["grpcSettings"]["serviceName"] == "service_name"


def test_build_transport_httpupgrade():
    """Test HTTPUpgrade transport for xray-core format."""
    stream = StreamSettings(network="httpupgrade", path="/upgrade", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["network"] == "httpupgrade"
    assert "httpupgradeSettings" in transport
    assert transport["httpupgradeSettings"]["path"] == "/upgrade"
    assert transport["httpupgradeSettings"]["host"] == "example.com"


def test_build_transport_tcp_with_http_header():
    """Test TCP with HTTP header for xray-core format."""
    stream = StreamSettings(network="tcp", header_type="http", path="/http", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    # xray-core converts tcp+http to http transport
    assert transport["network"] == "http"
    assert "httpSettings" in transport
    assert transport["httpSettings"]["path"] == "/http"
    assert transport["httpSettings"]["host"] == ["example.com"]


def test_build_transport_xhttp():
    """Test xHTTP (splithttp) transport for xray-core format."""
    stream = StreamSettings(network="xhttp", path="/xhttp", host="example.com")
    transport = stream.build_transport()
    assert transport is not None
    assert transport["network"] == "splithttp"
    assert "splithttpSettings" in transport
    assert transport["splithttpSettings"]["path"] == "/xhttp"
    assert transport["splithttpSettings"]["host"] == "example.com"


def test_build_tls_none():
    stream = StreamSettings(security="")
    assert stream.build_tls() is None


def test_build_tls_basic():
    """Test basic TLS settings for xray-core format."""
    stream = StreamSettings(security="tls", sni="example.com", allow_insecure=True)
    tls = stream.build_tls()
    assert tls is not None
    assert tls["allowInsecure"] is True
    assert tls["serverName"] == "example.com"


def test_build_tls_with_certificate():
    """Test TLS with certificate for xray-core format."""
    stream = StreamSettings(security="tls", certificate="cert_data")
    tls = stream.build_tls()
    assert tls is not None
    assert "certificates" in tls
    assert tls["certificates"][0]["certificate"] == "cert_data"


def test_build_tls_with_alpn():
    stream = StreamSettings(security="tls", alpn="h2,http/1.1")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["alpn"] == ["h2", "http/1.1"]


def test_build_reality():
    """Test Reality settings for xray-core format."""
    stream = StreamSettings(
        security="tls",
        sni="example.com",
        reality_public_key="pbk",
        reality_short_id="sid1,sid2",
        reality_spider_x="/",
    )
    reality = stream.build_reality()
    assert reality is not None
    assert reality["publicKey"] == "pbk"
    assert reality["shortId"] == "sid1"
    assert reality["serverName"] == "example.com"
    assert reality["spiderX"] == "/"
    # Default fingerprint should be set
    assert reality["fingerprint"] == "chrome"


def test_build_reality_with_fingerprint():
    """Test Reality with custom fingerprint."""
    stream = StreamSettings(
        reality_public_key="pbk",
        utls_fingerprint="firefox",
    )
    reality = stream.build_reality()
    assert reality is not None
    assert reality["fingerprint"] == "firefox"


def test_is_reality():
    """Test is_reality helper method."""
    stream = StreamSettings()
    assert stream.is_reality() is False

    stream.reality_public_key = "test_key"
    assert stream.is_reality() is True


def test_build_tls_with_utls_fingerprint():
    """Test TLS with uTLS fingerprint for xray-core format."""
    stream = StreamSettings(security="tls", utls_fingerprint="chrome")
    tls = stream.build_tls()
    assert tls is not None
    assert tls["fingerprint"] == "chrome"


def test_build_tls_skip_cert():
    """Test TLS with skip_cert for xray-core format."""
    stream = StreamSettings(security="tls", allow_insecure=False)
    tls = stream.build_tls(skip_cert=True)
    assert tls is not None
    assert tls["allowInsecure"] is True


def test_apply_to_outbound():
    """Test apply_to_outbound for xray-core format."""
    stream = StreamSettings(
        network="ws", path="/ws", security="tls", sni="example.com", packet_encoding="xudp"
    )
    outbound = {"protocol": "vmess"}
    stream.apply_to_outbound(outbound)
    assert "streamSettings" in outbound
    assert outbound["streamSettings"]["network"] == "ws"
    assert outbound["streamSettings"]["security"] == "tls"
    assert "tlsSettings" in outbound["streamSettings"]
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "example.com"
    assert outbound["settings"]["packetEncoding"] == "xudp"


def test_apply_to_outbound_vless():
    """Test apply_to_outbound for VLESS with packet encoding."""
    stream = StreamSettings(packet_encoding="xudp")
    outbound = {"protocol": "vless"}
    stream.apply_to_outbound(outbound)
    assert outbound["settings"]["packetEncoding"] == "xudp"


def test_apply_to_outbound_non_vmess_vless():
    """Test apply_to_outbound for non-vmess/vless (no packet encoding)."""
    stream = StreamSettings(packet_encoding="xudp")
    outbound = {"protocol": "trojan"}
    stream.apply_to_outbound(outbound)
    assert "settings" not in outbound or "packetEncoding" not in outbound.get("settings", {})


def test_apply_to_outbound_with_reality():
    """Test apply_to_outbound with Reality for xray-core format."""
    stream = StreamSettings(
        network="tcp",
        security="tls",
        sni="example.com",
        reality_public_key="test_public_key",
        reality_short_id="test_sid",
        utls_fingerprint="chrome",
    )
    outbound = {"protocol": "vless"}
    stream.apply_to_outbound(outbound)

    assert "streamSettings" in outbound
    ss = outbound["streamSettings"]
    assert ss["security"] == "reality"
    assert "realitySettings" in ss
    assert "tlsSettings" not in ss
    assert ss["realitySettings"]["publicKey"] == "test_public_key"
    assert ss["realitySettings"]["shortId"] == "test_sid"
    assert ss["realitySettings"]["serverName"] == "example.com"
    assert ss["realitySettings"]["fingerprint"] == "chrome"
