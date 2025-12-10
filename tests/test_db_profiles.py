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


def test_profile_manager_save_and_load(tmp_path):
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

    import src.db.profiles as profiles_mod
    from src import db as _db

    profiles_mod._get_protocol_classes = fake_protocols

    g = mgr.add_group("G")
    mgr.current_group_id = g.id
    mgr.add_profile(DummyBean())

    assert mgr.save() is True
    mgr2 = ProfileManager(profiles_dir=tmp_path)
    assert mgr2.load() is True
    assert any(gr.name == "G" for gr in mgr2.groups.values())
    assert len(mgr2.profiles) >= 1
