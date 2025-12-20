from dataclasses import dataclass
from typing import Any

from src.fmt.base import ProxyBean, format_address, is_ip_address


def test_is_ip_address():
    assert is_ip_address("127.0.0.1") is True
    assert is_ip_address("192.168.1.1") is True
    assert is_ip_address("::1") is True
    assert is_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334") is True
    assert is_ip_address("example.com") is False
    assert is_ip_address("not an ip") is False
    assert is_ip_address("") is False


def test_format_address():
    assert format_address("127.0.0.1", 1080) == "127.0.0.1:1080"
    assert format_address("example.com", 443) == "example.com:443"
    assert format_address("192.168.1.1", 8080) == "192.168.1.1:8080"


@dataclass
class DummyProxyBean(ProxyBean):
    @property
    def proxy_type(self) -> str:
        return "test"

    def to_share_link(self) -> str:
        return "test://link"

    def try_parse_link(self, link: str) -> bool:
        return link.startswith("test://")

    def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
        return {"type": "test", "server": self.server_address, "port": self.server_port}


def test_proxy_bean_display_address():
    bean = DummyProxyBean(server_address="127.0.0.1", server_port=1080)
    assert bean.display_address == "127.0.0.1:1080"


def test_proxy_bean_display_name_with_name():
    bean = DummyProxyBean(name="My Proxy", server_address="127.0.0.1", server_port=1080)
    assert bean.display_name == "My Proxy"


def test_proxy_bean_display_name_without_name():
    bean = DummyProxyBean(server_address="example.com", server_port=443)
    assert bean.display_name == "example.com:443"


def test_proxy_bean_display_type_and_name():
    bean = DummyProxyBean(name="Test", server_address="127.0.0.1", server_port=1080)
    assert bean.display_type_and_name == "[TEST] Test"


def test_proxy_bean_core_type():
    bean = DummyProxyBean()
    assert bean.core_type == "xray-core"


def test_proxy_bean_build_core_obj_xray_success():
    bean = DummyProxyBean(server_address="127.0.0.1", server_port=1080)
    result = bean.build_core_obj_singbox()
    assert "outbound" in result
    assert result["error"] == ""
    assert result["outbound"]["type"] == "test"
    assert result["outbound"]["server"] == "127.0.0.1"
    assert result["outbound"]["port"] == 1080


def test_proxy_bean_build_core_obj_xray_with_error():
    class FailingBean(DummyProxyBean):
        def build_outbound(self, skip_cert: bool = False) -> dict[str, Any]:
            raise ValueError("test error")

    bean = FailingBean()
    result = bean.build_core_obj_singbox()
    assert result["outbound"] == {}
    assert "test error" in result["error"]


def test_proxy_bean_to_tenga_share_link():
    bean = DummyProxyBean(name="Test", server_address="127.0.0.1", server_port=1080)
    link = bean.to_tenga_share_link()
    assert link.startswith("tenga://test#")
    assert len(link) > len("tenga://test#")


def test_proxy_bean_needs_external_core():
    bean = DummyProxyBean()
    assert bean.needs_external_core() == 0
    assert bean.needs_external_core(is_first_profile=False) == 0
