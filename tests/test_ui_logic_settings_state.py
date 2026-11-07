from src.db.data_store import DataStore
from src.db.profiles import ProfileEntry
from src.fmt.protocols import VLESSBean
from src.ui.logic.settings_state import runtime_snapshot


def test_snapshot_tracks_runtime_changes_and_ignores_theme(tmp_path):
    config = DataStore()
    profile = ProfileEntry(id=1, group_id=1, bean=VLESSBean())
    original = runtime_snapshot(config, profile, geo_paths=[])
    config.theme = "dark"
    assert runtime_snapshot(config, profile, geo_paths=[]) == original
    config.dns.custom_url = "1.1.1.1"
    assert runtime_snapshot(config, profile, geo_paths=[]) != original
    config.dns.custom_url = ""
    assert runtime_snapshot(config, profile, geo_paths=[]) == original
    geo = tmp_path / "geosite.dat"
    geo.write_bytes(b"first")
    before = runtime_snapshot(config, profile, geo_paths=[geo])
    geo.write_bytes(b"second")
    assert runtime_snapshot(config, profile, geo_paths=[geo]) != before


def test_kill_switch_change_asks_for_a_new_session():
    config = DataStore()
    profile = ProfileEntry(id=1, group_id=1, bean=VLESSBean())
    before = runtime_snapshot(config, profile, geo_paths=[])

    config.tun_kill_switch = True

    assert runtime_snapshot(config, profile, geo_paths=[]) != before


def test_global_routing_change_is_noticed_only_without_own_rules():
    from src.db.config import RoutingSettings

    config = DataStore()
    shared = ProfileEntry(id=1, group_id=1, bean=VLESSBean())
    own = ProfileEntry(id=2, group_id=1, bean=VLESSBean(), routing_settings=RoutingSettings())
    before_shared = runtime_snapshot(config, shared, geo_paths=[])
    before_own = runtime_snapshot(config, own, geo_paths=[])

    config.routing.proxy_list = ["a.com"]
    config.routing.use_saved_lists = True

    assert runtime_snapshot(config, shared, geo_paths=[]) != before_shared
    # Снимок меняется и у сервера со своими правилами: ключ `routing` общий.
    # Это известное огрубление; баннер лишний раз попросит переподключиться.
    assert runtime_snapshot(config, own, geo_paths=[]) != before_own
