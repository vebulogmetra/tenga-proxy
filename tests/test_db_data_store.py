from src.db.data_store import (
    DataStore,
    get_default_config_path,
    load_data_store,
    save_data_store,
)


def test_to_dict_excludes_runtime_fields():
    store = DataStore()
    store._core_token = "secret"
    store._core_running = True
    store._started_id = 123

    data = store.to_dict()
    assert "_core_token" not in data
    assert "_core_running" not in data
    assert "_started_id" not in data


def test_get_user_agent_default_and_custom():
    store = DataStore()

    assert "Tenga-proxy" in store.get_user_agent()

    store.user_agent = "MyAgent/1.0"
    assert store.get_user_agent() == "MyAgent/1.0"
    assert "Tenga-proxy" in store.get_user_agent(use_default=True)


def test_update_started_id_and_remember():
    store = DataStore()
    store.remember_enable = False

    store.update_started_id(10)
    assert store.started_id == 10
    assert store.remember_id == -1919

    store.remember_enable = True
    store.update_started_id(42)
    assert store.started_id == 42
    assert store.remember_id == 42


def test_default_config_path_is_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = get_default_config_path()
    assert str(path).endswith("settings.json")
    assert ".config" in str(path)


def test_load_and_save_data_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg_path = get_default_config_path()

    store = DataStore()
    store.inbound_address = "10.0.0.1"
    store.inbound_socks_port = 9999

    assert save_data_store(store, cfg_path) is True
    assert cfg_path.exists()

    loaded = load_data_store(cfg_path)
    assert isinstance(loaded, DataStore)
    assert loaded.inbound_address == "10.0.0.1"
    assert loaded.inbound_socks_port == 9999
