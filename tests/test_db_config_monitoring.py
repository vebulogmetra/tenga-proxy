from src.db.config import MonitoringSettings


def test_monitoring_settings_defaults():
    settings = MonitoringSettings()

    assert settings.enabled is True
    assert settings.check_interval_seconds == 10
    assert settings.test_url == "https://www.google.com/generate_204"


def test_monitoring_settings_custom_values():
    settings = MonitoringSettings(
        enabled=True,
        check_interval_seconds=30,
        test_url="https://example.com/test",
    )

    assert settings.enabled is True
    assert settings.check_interval_seconds == 30
    assert settings.test_url == "https://example.com/test"


def test_monitoring_settings_to_dict():
    settings = MonitoringSettings(
        enabled=True,
        check_interval_seconds=15,
        test_url="https://test.com",
    )

    data = settings.to_dict()

    assert data["enabled"] is True
    assert data["check_interval_seconds"] == 15
    assert data["test_url"] == "https://test.com"


def test_monitoring_settings_from_dict():
    data = {
        "enabled": True,
        "check_interval_seconds": 20,
        "test_url": "https://example.com",
    }

    settings = MonitoringSettings.from_dict(data)

    assert settings.enabled is True
    assert settings.check_interval_seconds == 20
    assert settings.test_url == "https://example.com"


def test_monitoring_settings_from_dict_partial():
    data = {
        "enabled": True,
    }

    settings = MonitoringSettings.from_dict(data)

    assert settings.enabled is True
    assert settings.check_interval_seconds == 10
    assert settings.test_url == "https://www.google.com/generate_204"


def test_monitoring_settings_to_json():
    settings = MonitoringSettings(enabled=True, check_interval_seconds=25)

    json_str = settings.to_json()

    assert "enabled" in json_str
    assert "true" in json_str.lower() or '"true"' in json_str
    assert "check_interval_seconds" in json_str
    assert "25" in json_str


def test_monitoring_settings_from_json():
    json_str = '{"enabled": true, "check_interval_seconds": 5, "test_url": "https://test.com"}'

    settings = MonitoringSettings.from_json(json_str)

    assert settings.enabled is True
    assert settings.check_interval_seconds == 5
    assert settings.test_url == "https://test.com"


def test_monitoring_settings_in_data_store(tmp_path):
    from src.db.data_store import DataStore

    store = DataStore()

    assert store.monitoring.enabled is True
    assert store.monitoring.check_interval_seconds == 10

    store.monitoring.enabled = True
    store.monitoring.check_interval_seconds = 30

    config_file = tmp_path / "settings.json"
    store.save(config_file)

    loaded = DataStore.load(config_file)

    assert loaded.monitoring.enabled is True
    assert loaded.monitoring.check_interval_seconds == 30
    assert loaded.monitoring.test_url == "https://www.google.com/generate_204"
