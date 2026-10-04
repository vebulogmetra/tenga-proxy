from src.db.data_store import (
    DEFAULT_USER_AGENT,
    DataStore,
    get_default_config_path,
    load_data_store,
    save_data_store,
)


def test_data_store_default_proxy_mode_is_tun():
    store = DataStore()
    assert store.proxy_mode == "tun"


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

    assert store.get_user_agent() == DEFAULT_USER_AGENT

    store.user_agent = "MyAgent/1.0"
    assert store.get_user_agent() == "MyAgent/1.0"
    assert store.get_user_agent(use_default=True) == DEFAULT_USER_AGENT


def test_default_user_agent_is_one_providers_recognise():
    """Незнакомому клиенту часть провайдеров рвёт соединение или отдаёт Clash YAML."""
    assert DEFAULT_USER_AGENT == "v2rayNG/1.8.23"
    assert "clash" not in DEFAULT_USER_AGENT.lower()


def test_the_old_default_user_agent_is_not_treated_as_a_custom_one():
    """Прежнее значение по умолчанию могло попасть в settings.json как «своё»."""
    store = DataStore()
    store.user_agent = "Tenga-proxy/1.0 (Prefer ClashMeta Format)"

    assert store.get_user_agent() == DEFAULT_USER_AGENT


def test_a_blank_user_agent_falls_back_to_the_default():
    store = DataStore()
    store.user_agent = "   "

    assert store.get_user_agent() == DEFAULT_USER_AGENT


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


def test_load_and_save_data_store_roundtrip_with_proxy_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg_path = get_default_config_path()

    store = DataStore()
    store.proxy_mode = "tun"
    store.tun_name = "xray0"
    store.tun_mtu = 1450

    assert save_data_store(store, cfg_path) is True

    loaded = load_data_store(cfg_path)
    assert loaded.proxy_mode == "tun"
    assert loaded.tun_name == "xray0"
    assert loaded.tun_mtu == 1450
