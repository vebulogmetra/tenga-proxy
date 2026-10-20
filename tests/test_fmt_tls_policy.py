import pytest

from src.fmt.stream import StreamSettings
from src.ui.logic.forms import validate_profile_link


@pytest.mark.parametrize(
    ("fingerprint", "expected"),
    [
        ("firefox", "firefox"),
        ("Chrome", "chrome"),
        ("unknown-fingerprint", "chrome"),
        ("HelloChrome_133", "hellochrome_133"),
    ],
)
def test_fingerprint_is_normalized_on_every_build(fingerprint, expected):
    stream = StreamSettings(
        security="tls", utls_fingerprint=fingerprint, reality_public_key="test-key"
    )
    assert stream.build_tls()["fingerprint"] == expected
    assert stream.build_reality()["fingerprint"] == expected
    assert stream.utls_fingerprint == fingerprint


def test_form_warning_is_distinct_from_error():
    result = validate_profile_link(
        "vless://uuid@example.com:443?security=tls&fp=made-up&allowInsecure=1"
    )
    assert result.ok
    assert result.warnings
    assert "Chrome" in " ".join(result.warnings)
