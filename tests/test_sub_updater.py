from dataclasses import dataclass
from unittest.mock import Mock, patch

from src.db.data_store import DataStore
from src.sub.updater import SubscriptionUpdater, update_subscription


@dataclass
class MockBean:
    display_name: str = "Test"
    proxy_type: str = "test"

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
