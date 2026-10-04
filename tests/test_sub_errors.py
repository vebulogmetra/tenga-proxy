"""Ошибки загрузки подписки: что показать пользователю вместо голого кода."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.sub.errors import (
    MAX_RESPONSE_SIZE,
    SubscriptionHttpError,
    SubscriptionTooLargeError,
    snippet_of,
)
from src.sub.updater import SubscriptionUpdater


def _http_error_response(status: int, body: str) -> Mock:
    response = Mock()
    response.status_code = status
    response.text = body
    response.content = body.encode("utf-8")
    response.encoding = "utf-8"
    response.headers = {"Content-Type": "text/plain; charset=utf-8"}
    response.raise_for_status = Mock(side_effect=requests.HTTPError(f"{status} Client Error"))
    return response


def test_snippet_collapses_whitespace_and_drops_control_characters():
    assert snippet_of("  Device\tlimit\r\n\r\n reached\x00\x07 ") == "Device limit reached"


def test_snippet_is_cut_to_200_characters():
    assert len(snippet_of("a" * 500)) == 200


@pytest.mark.parametrize("body", ["<html><body>403</body></html>", "  <!DOCTYPE html><html>"])
def test_snippet_ignores_html_pages(body):
    """Страница-заглушка CDN ничего не объясняет и только засоряет сообщение."""
    assert snippet_of(body) == ""


@pytest.mark.parametrize("body", [None, 12, Mock()])
def test_snippet_of_a_non_text_body_is_empty(body):
    assert snippet_of(body) == ""


@pytest.mark.parametrize("status", [403, 429])
def test_access_denied_error_shows_the_providers_explanation(status):
    error = SubscriptionHttpError(status, "Превышен лимит устройств")

    assert error.is_access_denied
    assert str(error) == f"HTTP {status}: Превышен лимит устройств"


def test_other_http_errors_show_only_the_code():
    error = SubscriptionHttpError(404, "Not Found")

    assert not error.is_access_denied
    assert str(error) == "HTTP 404"


def test_fetch_raises_http_error_with_the_body_snippet():
    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = _http_error_response(403, "Device limit reached\n")
        with pytest.raises(SubscriptionHttpError) as caught:
            SubscriptionUpdater().fetch("https://example.com/sub/secret-token")

    assert caught.value.status_code == 403
    assert caught.value.body_snippet == "Device limit reached"
    # Адрес подписки содержит токен: в тексте ошибки его быть не должно.
    assert "secret-token" not in str(caught.value)
    assert mock_get.call_count == 1


def test_http_error_is_still_a_requests_http_error():
    """Код, который ловит requests.HTTPError, не должен сломаться."""
    assert issubclass(SubscriptionHttpError, requests.HTTPError)


def test_fetch_rejects_a_response_over_the_size_limit():
    response = Mock()
    response.text = "x" * (MAX_RESPONSE_SIZE + 1)
    response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.requests.get", return_value=response) as mock_get,
        pytest.raises(SubscriptionTooLargeError),
    ):
        SubscriptionUpdater().fetch("https://example.com/sub")

    # Слишком большой ответ — окончательный: повтор вернёт то же самое.
    assert mock_get.call_count == 1


def test_size_limit_is_ten_megabytes():
    assert MAX_RESPONSE_SIZE == 10 * 1024 * 1024
