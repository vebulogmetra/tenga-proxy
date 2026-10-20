import io
import logging

import pytest

from src.core.log_redaction import RedactingFormatter, redact


@pytest.mark.parametrize(
    "secret_text",
    [
        "ss://c2VjcmV0cGFzc3dvcmQ=",
        "vmess://eyJpZCI6InNlY3JldCJ9",
        "vless://secret@host:443",
        "trojan://secret",
        "hy2://secret@host",
        "ssr://c2VjcmV0",
        "Authorization: Bearer secret",
        '"password": "secret"',
        "https://provider.example/sub/secret?token=secret",
        "https://user:secret@provider.example/sub",
        "auth=secret",
        "X-HWID: secret",
    ],
)
def test_secret_is_redacted(secret_text):
    assert "secret" not in redact(secret_text)
    assert redact(secret_text) != secret_text


def test_plain_text_survives():
    assert (
        redact("Connection failed: timeout after 30 seconds")
        == "Connection failed: timeout after 30 seconds"
    )


def test_traceback_and_interpolated_args_are_sanitized():
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.Logger("isolated")
    logger.addHandler(handler)
    try:
        raise ValueError("https://provider.example/sub/secret")
    except ValueError:
        logger.exception("Connection %s", "trojan://secret@host:443")
    assert "secret" not in output.getvalue()
    assert "ValueError" in output.getvalue()


@pytest.mark.parametrize(
    "text",
    ['{"Authorization": "Bearer secret"}', 'username="secret"', "Bearer secret", "id=secret"],
)
def test_structured_credentials_are_redacted(text):
    assert "secret" not in redact(text)


def test_json_basic_authorization_is_redacted():
    assert "dXNlcjpwYXNz" not in redact('{"Authorization": "Basic dXNlcjpwYXNz"}')


def test_escaped_json_password_is_redacted_completely():
    assert "tailsecret" not in redact(r'{"password": "prefix\"tailsecret"}')
