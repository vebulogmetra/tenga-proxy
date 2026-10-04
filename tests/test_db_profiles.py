from dataclasses import dataclass

from src.db.profiles import (
    ProfileEntry,
    ProfileGroup,
    ProfileManager,
)


def test_profile_entry_name_and_type():
    @dataclass
    class DummyBean:
        display_name: str = "Test Proxy"
        proxy_type: str = "dummy"

        def to_dict(self) -> dict[str, str]:
            return {"k": "v"}

    bean = DummyBean()
    entry = ProfileEntry(id=1, group_id=2, bean=bean)

    assert entry.name == "Test Proxy"
    assert entry.proxy_type == "dummy"

    data = entry.to_dict()
    assert data["id"] == 1
    assert data["group_id"] == 2
    assert data["type"] == "dummy"
    assert data["bean"] == {"k": "v"}


def test_profile_entry_from_dict_unknown_type(capsys):
    data = {"type": "unknown", "bean": {}}
    entry = ProfileEntry.from_dict(data)
    assert entry is None

    captured = capsys.readouterr()
    assert "Unknown protocol type" in captured.out


def test_profile_entry_from_dict_with_fake_protocol(monkeypatch):
    @dataclass
    class FakeBean:
        display_name: str = "X"
        proxy_type: str = "fake"

        @classmethod
        def from_dict(cls, data):
            return cls()

        def to_dict(self):
            return {"ok": True}

    def fake_protocols():
        return {"fake": FakeBean}

    monkeypatch.setattr("src.db.profiles._get_protocol_classes", lambda: fake_protocols())

    data = {
        "id": 7,
        "group_id": 3,
        "type": "fake",
        "bean": {},
        "latency_ms": 123,
        "last_used": 456,
    }
    entry = ProfileEntry.from_dict(data)
    assert entry is not None
    assert entry.id == 7
    assert entry.group_id == 3
    assert entry.latency_ms == 123
    assert entry.last_used == 456
    assert isinstance(entry.bean, FakeBean)


def test_profile_group_defaults_and_serialization():
    group = ProfileGroup()
    d = group.to_dict()
    assert d["id"] == 0
    assert d["name"] == "Default"
    assert d["is_subscription"] is False

    json_str = group.to_json()
    assert '"name": "Default"' in json_str


def test_profile_manager_basic_operations(tmp_path):
    mgr = ProfileManager(profiles_dir=tmp_path)

    @dataclass
    class DummyBean:
        display_name: str = "P1"
        proxy_type: str = "dummy"

        def to_dict(self):
            return {}

    g1 = mgr.add_group("G1")
    g2 = mgr.add_group("G2", is_subscription=True)
    assert g1.id != g2.id
    assert mgr.get_group(g1.id) is g1

    mgr.current_group_id = g1.id
    p1 = mgr.add_profile(DummyBean())
    assert p1.group_id == g1.id
    assert mgr.get_profile(p1.id) is p1

    profiles_g1 = mgr.get_profiles_in_group(g1.id)
    assert len(profiles_g1) == 1 and profiles_g1[0] is p1

    assert mgr.remove_profile(p1.id) is True
    assert mgr.get_profile(p1.id) is None

    assert mgr.remove_group(g2.id, remove_profiles=True) is True
    assert mgr.get_group(g2.id) is None


def test_profile_manager_save_and_load(tmp_path, monkeypatch):
    mgr = ProfileManager(profiles_dir=tmp_path)

    @dataclass
    class DummyBean:
        display_name: str = "Persisted"
        proxy_type: str = "dummy"

        def to_dict(self):
            return {"x": 1}

        @classmethod
        def from_dict(cls, data):
            return cls()

    def fake_protocols():
        return {"dummy": DummyBean}

    # Через monkeypatch, а не прямым присваиванием: иначе фейковый реестр протоколов
    # утекал бы в последующие тесты и ломал разбор реальных профилей.
    monkeypatch.setattr("src.db.profiles._get_protocol_classes", fake_protocols)

    g = mgr.add_group("G")
    mgr.current_group_id = g.id
    mgr.add_profile(DummyBean())

    assert mgr.save() is True
    mgr2 = ProfileManager(profiles_dir=tmp_path)
    assert mgr2.load() is True
    assert any(gr.name == "G" for gr in mgr2.groups.values())
    assert len(mgr2.profiles) >= 1


def test_last_used_profile_is_the_latest_marked(tmp_path):
    mgr = ProfileManager(profiles_dir=tmp_path)

    @dataclass
    class DummyBean:
        display_name: str = "P"
        proxy_type: str = "dummy"

        def to_dict(self):
            return {}

    assert mgr.last_used_profile() is None

    first = mgr.add_profile(DummyBean())
    second = mgr.add_profile(DummyBean())
    assert mgr.last_used_profile() is None

    mgr.mark_used(second.id, now=100)
    mgr.mark_used(first.id, now=200)
    assert mgr.last_used_profile() is first

    mgr.remove_profile(first.id)
    assert mgr.last_used_profile() is second


def test_marking_a_missing_profile_is_harmless(tmp_path):
    mgr = ProfileManager(profiles_dir=tmp_path)
    mgr.mark_used(42)
    assert mgr.last_used_profile() is None


# --- sync_group: обновление подписки без смены id -----------------------------


def _vless(name: str, server: str = "a.example.org", port: int = 443, uuid: str = "u-1"):
    from src.fmt.protocols import VLESSBean

    return VLESSBean(name=name, server_address=server, server_port=port, uuid=uuid)


def test_profile_match_key_is_name_type_server_port():
    from src.db.profiles import profile_match_key

    assert profile_match_key(_vless("NL-1")) == "NL-1|vless|a.example.org|443"


def test_sync_group_keeps_id_and_user_data_of_a_matched_profile(tmp_path):
    from src.db.config import RoutingSettings, VpnSettings

    manager = ProfileManager(profiles_dir=tmp_path)
    group = manager.add_group("Sub", is_subscription=True)
    entry = manager.add_profile(_vless("NL-1", uuid="old"), group.id)
    entry.latency_ms = 87
    entry.last_used = 1_700_000_000
    entry.vpn_settings = VpnSettings()
    entry.routing_settings = RoutingSettings()

    manager.sync_group(group.id, [_vless("NL-1", uuid="new")])

    synced = manager.get_profiles_in_group(group.id)
    assert [p.id for p in synced] == [entry.id]
    assert synced[0].bean.uuid == "new"
    assert synced[0].latency_ms == 87
    assert synced[0].last_used == 1_700_000_000
    assert synced[0].vpn_settings is entry.vpn_settings
    assert synced[0].routing_settings is entry.routing_settings


def test_sync_group_adds_new_and_removes_missing_profiles(tmp_path):
    manager = ProfileManager(profiles_dir=tmp_path)
    group = manager.add_group("Sub", is_subscription=True)
    kept = manager.add_profile(_vless("NL-1"), group.id)
    gone = manager.add_profile(_vless("DE-1", server="b.example.org"), group.id)

    result = manager.sync_group(group.id, [_vless("NL-1"), _vless("FI-1", server="c.example.org")])

    names = {p.name: p.id for p in manager.get_profiles_in_group(group.id)}
    assert set(names) == {"NL-1", "FI-1"}
    assert names["NL-1"] == kept.id
    assert names["FI-1"] not in (kept.id, gone.id)
    assert manager.get_profile(gone.id) is None
    assert (result.updated, result.added, result.removed) == (1, 1, 1)


def test_sync_group_follows_the_order_of_the_response(tmp_path):
    manager = ProfileManager(profiles_dir=tmp_path)
    group = manager.add_group("Sub", is_subscription=True)
    manager.add_profile(_vless("B"), group.id)
    manager.add_profile(_vless("C"), group.id)

    manager.sync_group(group.id, [_vless("A"), _vless("C"), _vless("B")])

    assert [p.name for p in manager.get_profiles_in_group(group.id)] == ["A", "C", "B"]


def test_sync_group_does_not_touch_other_groups(tmp_path):
    manager = ProfileManager(profiles_dir=tmp_path)
    group = manager.add_group("Sub", is_subscription=True)
    other = manager.add_group("Manual")
    manual = manager.add_profile(_vless("NL-1"), other.id)

    manager.sync_group(group.id, [_vless("NL-1")])

    assert manager.get_profile(manual.id) is manual
    assert [p.id for p in manager.get_profiles_in_group(other.id)] == [manual.id]
    assert len(manager.get_profiles_in_group(group.id)) == 1


def test_sync_group_keeps_duplicates_from_the_response(tmp_path):
    """Два одинаковых ключа в ответе — два профиля, как и до перехода на upsert."""
    manager = ProfileManager(profiles_dir=tmp_path)
    group = manager.add_group("Sub", is_subscription=True)
    first = manager.add_profile(_vless("NL-1", uuid="a"), group.id)

    manager.sync_group(group.id, [_vless("NL-1", uuid="a"), _vless("NL-1", uuid="b")])

    synced = manager.get_profiles_in_group(group.id)
    assert len(synced) == 2
    assert synced[0].id == first.id
    assert synced[1].id != first.id
