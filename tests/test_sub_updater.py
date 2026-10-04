from dataclasses import dataclass
from unittest.mock import Mock, patch

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

    mock_response = Mock()
    mock_response.text = "test content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater(config=config)
        result = updater.fetch("http://example.com/sub")
        assert result == "test content"
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["User-Agent"] == "CustomAgent/1.0"
        assert call_kwargs["timeout"] == 30
        assert call_kwargs["verify"] is True


def test_subscription_updater_fetch_without_config(monkeypatch):
    mock_response = Mock()
    mock_response.text = "content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater()
        result = updater.fetch("http://example.com/sub")
        assert result == "content"
        call_kwargs = mock_get.call_args[1]
        assert "User-Agent" not in call_kwargs.get("headers", {})


def test_subscription_updater_fetch_with_insecure(monkeypatch):
    config = DataStore()
    config.sub_insecure = True

    mock_response = Mock()
    mock_response.text = "content"
    mock_response.raise_for_status = Mock()

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = mock_response
        updater = SubscriptionUpdater(config=config)
        updater.fetch("http://example.com/sub")
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

    mock_response = Mock()
    mock_response.text = "vmess://test"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        updater = SubscriptionUpdater(config=config, profiles=profiles)
        result = updater.update("http://example.com/sub", group_id=group.id, clear_existing=True)

        assert len(result) == 1
        group_profiles = profiles.get_profiles_in_group(group.id)
        assert len(group_profiles) == 1
        assert group_profiles[0].bean.display_name == "Test"


def test_subscription_updater_update_without_profiles(monkeypatch):
    mock_response = Mock()
    mock_response.text = "content"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        updater = SubscriptionUpdater()
        result = updater.update("http://example.com/sub")

        assert len(result) == 1


def test_update_subscription_helper(monkeypatch):
    mock_response = Mock()
    mock_response.text = "content"
    mock_response.raise_for_status = Mock()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.parse_subscription_content") as mock_parse,
    ):
        mock_get.return_value = mock_response
        mock_bean = MockBean()
        mock_parse.return_value = [mock_bean]

        result = update_subscription("http://example.com/sub")

        assert len(result) == 1


def test_fetch_assumes_utf8_when_the_server_omits_the_charset():
    """requests falls back to ISO-8859-1 per RFC, mangling non-ASCII names."""
    from unittest.mock import Mock, patch

    from src.sub.updater import SubscriptionUpdater

    name = "🌏 ByPass №3"
    body = f"vless://uuid@example.org:443#{name}".encode()

    mock_response = Mock()
    mock_response.content = body
    mock_response.encoding = "ISO-8859-1"  # так requests трактует ответ без charset
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.raise_for_status = Mock()
    mock_response.text = body.decode("iso-8859-1")

    with patch("requests.get", return_value=mock_response):
        result = SubscriptionUpdater().fetch("http://example.com/sub")

    assert name in result


def test_fetch_respects_an_explicit_charset():
    """A server that does declare its charset must be believed."""
    from unittest.mock import Mock, patch

    from src.sub.updater import SubscriptionUpdater

    text = "vless://uuid@example.org:443#Проба"
    mock_response = Mock()
    mock_response.content = text.encode("utf-8")
    mock_response.encoding = "utf-8"
    mock_response.headers = {"Content-Type": "text/plain; charset=utf-8"}
    mock_response.raise_for_status = Mock()
    mock_response.text = text

    with patch("requests.get", return_value=mock_response):
        result = SubscriptionUpdater().fetch("http://example.com/sub")

    assert result == text


# --- Обновление без смены id --------------------------------------------------

LINK_NL = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"
LINK_DE = "vless://22222222-2222-2222-2222-222222222222@de.example.org:443?type=tcp#DE-1"


def _text_response(text: str) -> Mock:
    response = Mock()
    response.text = text
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

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = _text_response(f"{LINK_NL}\n{LINK_DE}")
        updater.update("http://example.com/sub", group_id=group.id)
        before = {p.name: p for p in profiles.get_profiles_in_group(group.id)}
        before["NL-1"].latency_ms = 42

        mock_get.return_value = _text_response(LINK_NL)
        updater.update("http://example.com/sub", group_id=group.id)

    after = profiles.get_profiles_in_group(group.id)
    assert [p.name for p in after] == ["NL-1"]
    assert after[0].id == before["NL-1"].id
    assert after[0].latency_ms == 42


def test_update_with_an_empty_response_leaves_the_group_alone(tmp_path):
    """Пустой ответ — сбой провайдера, а не «серверов больше нет»."""
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = _text_response(LINK_NL)
        updater.update("http://example.com/sub", group_id=group.id)
        mock_get.return_value = _text_response("<html>maintenance</html>")
        assert updater.update("http://example.com/sub", group_id=group.id) == []

    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1"]


def test_update_without_clearing_appends_to_the_group(tmp_path):
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = _text_response(LINK_NL)
        updater.update("http://example.com/sub", group_id=group.id)
        updater.update("http://example.com/sub", group_id=group.id, clear_existing=False)

    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["NL-1", "NL-1"]


# --- Время обновления ---------------------------------------------------------


def test_update_records_when_the_subscription_was_refreshed(tmp_path):
    profiles, group = _subscription(tmp_path)
    updater = SubscriptionUpdater(profiles=profiles)

    with (
        patch("src.sub.updater.requests.get", return_value=_text_response(LINK_NL)),
        patch("src.sub.updater.time.time", return_value=1_800_000_000.7),
    ):
        updater.update("http://example.com/sub", group_id=group.id)

    assert group.last_updated == 1_800_000_000


def test_an_empty_response_does_not_count_as_a_refresh(tmp_path):
    profiles, group = _subscription(tmp_path)
    group.last_updated = 1_700_000_000
    updater = SubscriptionUpdater(profiles=profiles)

    with patch("src.sub.updater.requests.get", return_value=_text_response("nothing here")):
        updater.update("http://example.com/sub", group_id=group.id)

    assert group.last_updated == 1_700_000_000


# --- Метаданные ---------------------------------------------------------------


def _response_with_headers(text: str, headers: dict[str, str]) -> Mock:
    response = _text_response(text)
    response.headers = headers
    response.content = text.encode("utf-8")
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

    with patch("src.sub.updater.requests.get", return_value=response):
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

    with patch("src.sub.updater.requests.get", return_value=response):
        SubscriptionUpdater(profiles=profiles).update("http://example.com/sub", group_id=group.id)

    from src.db.profiles import ProfileManager

    reloaded = ProfileManager(profiles_dir=tmp_path)
    reloaded.load()
    assert reloaded.get_group(group.id).sub_user_info == (
        "upload=5; download=5; total=10; expire=1700000000"
    )


def test_fetch_response_returns_the_headers_next_to_the_text():
    response = _response_with_headers(LINK_NL, {"profile-update-interval": "6"})

    with patch("src.sub.updater.requests.get", return_value=response):
        fetched = SubscriptionUpdater().fetch_response("http://example.com/sub")

    assert fetched.content == LINK_NL
    assert fetched.headers["profile-update-interval"] == "6"
