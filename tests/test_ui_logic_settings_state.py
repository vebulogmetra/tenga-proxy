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
