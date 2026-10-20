from src.ui.logic.settings_form import validate_settings


def test_invalid_fragment_is_reported_without_mutating_config():
    from src.db.data_store import DataStore

    config = DataStore()
    config.tls_fragment.length = "0-100"
    assert "fragment_length" in validate_settings(config)
    assert config.tls_fragment.length == "0-100"


def test_default_settings_are_valid():
    from src.db.data_store import DataStore

    assert validate_settings(DataStore()) == {}
