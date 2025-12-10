from pathlib import Path

from src.core.context import (
    AppContext,
    ProxyState,
    get_context,
    init_context,
    reset_context,
)


def test_proxy_state_listeners_called():
    state = ProxyState()
    calls = []

    def listener(s: ProxyState) -> None:
        calls.append((s.is_running, s.started_profile_id))

    state.add_listener(listener)

    state.set_running(42)
    state.set_stopped()

    assert calls == [(True, 42), (False, -1)]


def test_proxy_state_remove_listener():
    state = ProxyState()
    calls = []

    def listener(s: ProxyState) -> None:
        calls.append(s.is_running)

    state.add_listener(listener)
    state.set_running(1)
    state.remove_listener(listener)
    state.set_stopped()

    assert calls == [True]


def test_app_context_uses_custom_config_dir(tmp_path):
    config_dir = tmp_path / "config"
    ctx = AppContext(config_dir=config_dir)

    assert ctx.config_dir == config_dir
    assert config_dir.exists()


def test_app_context_lazy_load_config(monkeypatch, tmp_path):
    from src.db import data_store as real_data_store

    saved_paths = []

    class FakeDataStore:
        def __init__(self) -> None:
            self.saved = False

        @classmethod
        def load(cls, path: Path) -> "FakeDataStore":
            instance = cls()
            instance.loaded_from = path
            return instance

        def save(self, path: Path) -> bool:
            self.saved = True
            saved_paths.append(path)
            return True

    monkeypatch.setattr(real_data_store, "DataStore", FakeDataStore)

    ctx = AppContext(config_dir=tmp_path)

    config = ctx.config
    assert isinstance(config, FakeDataStore)
    assert hasattr(config, "loaded_from")
    assert config.loaded_from == tmp_path / "settings.json"

    assert ctx.save_config() is True
    assert saved_paths == [tmp_path / "settings.json"]


def test_app_context_lazy_load_profiles(monkeypatch, tmp_path):
    from src.db import profiles as real_profiles

    calls = {"load": 0, "save": 0}

    class FakeProfileManager:
        def __init__(self, profiles_dir: Path) -> None:
            self.profiles_dir = profiles_dir

        def load(self) -> None:
            calls["load"] += 1

        def save(self) -> bool:
            calls["save"] += 1
            return True

    monkeypatch.setattr(real_profiles, "ProfileManager", FakeProfileManager)

    ctx = AppContext(config_dir=tmp_path)

    profiles = ctx.profiles
    assert isinstance(profiles, FakeProfileManager)
    assert profiles.profiles_dir == tmp_path / "profiles"
    assert calls["load"] == 1

    assert ctx.save_profiles() is True
    assert calls["save"] == 1


def test_context_singleton_lifecycle(tmp_path):
    reset_context()

    ctx1 = get_context()
    ctx2 = get_context()
    assert ctx1 is ctx2

    new_ctx = init_context(config_dir=tmp_path)
    assert new_ctx is get_context()
    assert new_ctx.config_dir == tmp_path

    reset_context()
    ctx3 = get_context()
    assert ctx3 is not new_ctx
