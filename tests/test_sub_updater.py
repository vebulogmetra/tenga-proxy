from dataclasses import dataclass
from unittest.mock import Mock, patch

import requests

from src.db.data_store import DataStore
from src.sub.updater import SubscriptionUpdater, update_subscription


@dataclass
class MockBean:
    display_name: str = "Test"
    proxy_type: str = "test"
    name: str = "Test"
    server_address: str = "example.com"
    server_port: int = 443

    def to_dict(self) -> dict[str, str]:
        return {"type": "test"}


def test_subscription_updater_fetch_with_user_agent(monkeypatch):
    config = DataStore()
    config.user_agent = "CustomAgent/1.0"

    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"test content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater(config=config)
        result = updater.fetch("https://example.com/sub")
        assert result == "test content"
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["User-Agent"] == "CustomAgent/1.0"
        assert call_kwargs["timeout"] == 30
        assert call_kwargs["verify"] is True


def test_subscription_updater_fetch_without_config(monkeypatch):
    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater()
        result = updater.fetch("https://example.com/sub")
        assert result == "content"
        call_kwargs = mock_get.call_args[1]
        assert "User-Agent" not in call_kwargs.get("headers", {})


def test_subscription_updater_fetch_with_insecure(monkeypatch):
    config = DataStore()
    config.sub_insecure = True

    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater(config=config)
        updater.fetch("https://example.com/sub")
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["verify"] is False


def test_subscription_updater_parse(monkeypatch):
    with patch("src.sub.updater.parse_subscription_content") as mock_parse:
        mock_beans = [MockBean()]
        mock_parse.return_value = mock_beans
        updater = SubscriptionUpdater()
        result = updater.parse("test content")
        assert result == mock_beans
        mock_parse.assert_called_once_with("test content")


def test_subscription_updater_update_with_profiles(monkeypatch, tmp_path):
    config = DataStore()
    from src.db.profiles import ProfileManager

    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Test Group")
    profiles.current_group_id = group.id

    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"vmess://test"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.pinned_get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        updater = SubscriptionUpdater(config=config, profiles=profiles)
        result = updater.update("https://example.com/sub", group_id=group.id, clear_existing=True)

        assert len(result) == 1
        group_profiles = profiles.get_profiles_in_group(group.id)
        assert len(group_profiles) == 1
        assert group_profiles[0].bean.display_name == "Test"


def test_subscription_updater_update_without_profiles(monkeypatch):
    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"content"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.pinned_get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        updater = SubscriptionUpdater()
        result = updater.update("https://example.com/sub")

        assert len(result) == 1


def test_update_subscription_helper(monkeypatch):
    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = b"content"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.pinned_get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        result = update_subscription("https://example.com/sub")

        assert len(result) == 1


def test_fetch_assumes_utf8_when_the_server_omits_the_charset():
    """requests falls back to ISO-8859-1 per RFC, mangling non-ASCII names."""
    from unittest.mock import Mock, patch

    from src.sub.updater import SubscriptionUpdater

    name = "🌏 ByPass №3"
    body = f"vless://uuid@example.org:443#{name}".encode()

    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = body
    mock_response.encoding = "ISO-8859-1"  # так requests трактует ответ без charset
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.pinned_get", return_value=mock_response):
        result = SubscriptionUpdater().fetch("https://example.com/sub")

    assert name in result


def test_fetch_respects_an_explicit_charset():
    """A server that does declare its charset must be believed."""
    from unittest.mock import Mock, patch

    from src.sub.updater import SubscriptionUpdater

    text = "vless://uuid@example.org:443#Проба"
    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b""
    mock_response._content_consumed = True
    mock_response.encoding = "utf-8"
    mock_response._content = text.encode("utf-8")
    mock_response.encoding = "utf-8"
    mock_response.headers = {"Content-Type": "text/plain; charset=utf-8"}
    mock_response.raise_for_status = Mock()
    mock_response._content = (text).encode("utf-8")

    with patch("src.sub.updater.pinned_get", return_value=mock_response):
        result = SubscriptionUpdater().fetch("https://example.com/sub")

    assert result == text


# --- Обновление без смены id --------------------------------------------------

LINK_NL = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"
LINK_DE = "vless://22222222-2222-2222-2222-222222222222@de.example.org:443?type=tcp#DE-1"


def _text_response(text: str) -> Mock:
    response = requests.Response()
    response.status_code = 200
    response._content = b""
    response._content_consumed = True
    response.encoding = "utf-8"
    response._content = (text).encode("utf-8")
    response.raise_for_status = Mock()
    return response


def _subscription(tmp_path):
    from src.db.profiles import ProfileManager

    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Sub", is_subscription=True)
    return profiles, group


def test_update_keeps_the_id_and_latency_of_a_profile_still_in_the_response(tmp_path):
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = _text_response(f"{LINK_NL}\n{LINK_DE}")
        updater.update("https://example.com/sub", group_id=group.id)
        before = {p.name: p for p in profiles.get_profiles_in_group(group.id)}
        before["NL-1"].latency_ms = 42

        mock_get.return_value = _text_response(LINK_NL)
        updater.update("https://example.com/sub", group_id=group.id)

    after = profiles.get_profiles_in_group(group.id)
    assert [p.name for p in after] == ["NL-1"]
    assert after[0].id == before["NL-1"].id
    assert after[0].latency_ms == 42


def test_update_with_an_empty_response_leaves_the_group_alone(tmp_path):
    """Пустой ответ — сбой провайдера, а не «серверов больше нет»."""
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = _text_response(LINK_NL)
        updater.update("https://example.com/sub", group_id=group.id)
        mock_get.return_value = _text_response("<html>maintenance</html>")
        assert updater.update("https://example.com/sub", group_id=group.id) == []

    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1"]


def test_update_without_clearing_appends_to_the_group(tmp_path):
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = _text_response(LINK_NL)
        updater.update("https://example.com/sub", group_id=group.id)
        updater.update("https://example.com/sub", group_id=group.id, clear_existing=False)

    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1", "NL-1"]


# --- Время обновления ---------------------------------------------------------


def test_update_records_when_the_subscription_was_refreshed(tmp_path):
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with (
        patch("src.sub.updater.pinned_get", return_value=_text_response(LINK_NL)),
        patch("src.sub.updater.time.time", return_value=1_800_000_000.7),
    ):
        updater.update("https://example.com/sub", group_id=group.id)

    assert group.last_updated == 1_800_000_000


def test_an_empty_response_does_not_count_as_a_refresh(tmp_path):
    profiles, group = _subscription(tmp_path)
    group.last_updated = 1_700_000_000
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.pinned_get", return_value=_text_response("nothing here")):
        updater.update("https://example.com/sub", group_id=group.id)

    assert group.last_updated == 1_700_000_000


# --- Метаданные ---------------------------------------------------------------


def _response_with_headers(text: str, headers: dict[str, str]) -> Mock:
    response = _text_response(text)
    response.headers = headers
    response._content = text.encode("utf-8")
    response.encoding = None
    return response


def test_update_saves_what_the_provider_says_about_the_subscription(tmp_path):
    profiles, group = _subscription(tmp_path)
    group.subscription_url = "https://provider.example/sub/token"
    group.name = "provider.example"
    response = _response_with_headers(
        f"#announce: Техработы\n{LINK_NL}",
        {
            "Subscription-Userinfo": "upload=1; download=2; total=3; expire=4",
            "Profile-Title": "Быстрый VPN",
            "Content-Type": "text/plain",
        },
    )

    with patch("src.sub.updater.pinned_get", return_value=response):
        SubscriptionUpdater(profiles=profiles).update(group.subscription_url, group_id=group.id)

    assert group.sub_user_info == "upload=1; download=2; total=3; expire=4"
    assert group.sub_announce == "Техработы"
    assert group.name == "Быстрый VPN"


def test_metadata_is_saved_even_when_the_response_has_no_servers(tmp_path):
    """Истёкшая подписка отдаёт пустой список, но срок и объявление — в заголовках."""
    profiles, group = _subscription(tmp_path)
    response = _response_with_headers(
        "", {"subscription-userinfo": "upload=5; download=5; total=10; expire=1700000000"}
    )

    with patch("src.sub.updater.pinned_get", return_value=response):
        SubscriptionUpdater(profiles=profiles).update("https://example.com/sub", group_id=group.id)

    from src.db.profiles import ProfileManager

    reloaded = ProfileManager(profiles_dir=tmp_path)
    reloaded.load()
    assert reloaded.get_group(group.id).sub_user_info == (
        "upload=5; download=5; total=10; expire=1700000000"
    )


def test_empty_response_keeps_the_servers_and_flags_the_group(tmp_path):
    """Панель отдаёт просроченному пользователю 200 с пустым телом и ссылкой на продление."""
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)
    renew = "https://provider.example/renew"

    with patch("src.sub.updater.pinned_get") as mock_get:
        mock_get.return_value = _text_response(LINK_NL)
        updater.update("https://example.com/sub", group_id=group.id)
        assert group.sub_empty is False
        mock_get.return_value = _response_with_headers("", {"Profile-Web-Page-Url": renew})
        updater.update("https://example.com/sub", group_id=group.id)

    assert group.sub_empty is True
    assert group.sub_web_page_url == renew
    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1"]


def test_servers_in_the_next_response_clear_the_empty_flag(tmp_path):
    profiles, group = _subscription(tmp_path)
    group.sub_empty = True

    with patch("src.sub.updater.pinned_get", return_value=_text_response(LINK_NL)):
        SubscriptionUpdater(profiles=profiles).update("https://example.com/sub", group_id=group.id)

    assert group.sub_empty is False


def test_failed_update_keeps_the_decoration_and_the_flag(tmp_path):
    profiles, group = _subscription(tmp_path)
    group.sub_announce = "Продлите до пятницы"
    group.sub_web_page_url = "https://provider.example/renew"
    group.sub_empty = True
    response = _text_response("unavailable")
    response.status_code = 503
    response.raise_for_status = Mock(side_effect=requests.HTTPError("503"))

    with patch("src.sub.updater.pinned_get", return_value=response):
        try:
            SubscriptionUpdater(profiles=profiles).update(
                "https://example.com/sub", group_id=group.id
            )
        except requests.RequestException:
            pass

    assert group.sub_announce == "Продлите до пятницы"
    assert group.sub_web_page_url == "https://provider.example/renew"
    assert group.sub_empty is True


def test_fetch_response_returns_the_headers_next_to_the_text():
    response = _response_with_headers(LINK_NL, {"profile-update-interval": "6"})

    with patch("src.sub.updater.pinned_get", return_value=response):
        fetched = SubscriptionUpdater().fetch_response("https://example.com/sub")

    assert fetched.content == LINK_NL
    assert fetched.headers["profile-update-interval"] == "6"
