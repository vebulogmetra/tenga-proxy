"""Импорт общей маршрутизации: что показать, что применить, как откатить."""

from __future__ import annotations

from src.db.config import RoutingMode, RoutingSettings
from src.db.data_store import DataStore
from src.ui.logic.routing_import import (
    ImportRow,
    apply_import,
    effective_routing,
    import_rows,
    restore_backup,
)


def _legacy(tmp_path) -> DataStore:
    """Старая установка: списки в файлах, в памяти их нет до подключения."""
    (tmp_path / "direct_list.txt").write_text("old.example\n", encoding="utf-8")
    return DataStore()


def test_effective_routing_reads_legacy_files_without_touching_config(tmp_path):
    config = _legacy(tmp_path)
    routing = effective_routing(config.routing, tmp_path)
    assert routing.direct_list == ["old.example"]
    assert config.routing.direct_list == []


def test_rows_count_removals_from_legacy_files(tmp_path):
    config = _legacy(tmp_path)
    new = RoutingSettings(direct_list=["new.example"])
    rows = import_rows(
        effective_routing(config.routing, tmp_path), new, name="", direct_default=False
    )
    direct = next(r for r in rows if r.label == "Напрямую")
    assert direct.value == "1 правило: +1, −1"
    assert direct.details == ("+ new.example", "− old.example")


def test_rows_name_profile_and_rest_of_traffic():
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="RU", direct_default=False)
    assert rows[0] == ImportRow("Профиль", "RU")
    rest = next(r for r in rows if r.label == "Остальное")
    assert rest == ImportRow("Остальное", "через прокси")


def test_direct_default_request_is_flagged_on_the_rest_row():
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="", direct_default=True)
    assert rows[0].label != "Профиль"
    rest = next(r for r in rows if r.label == "Остальное")
    assert rest.warning
    assert rest.value == (
        "через прокси. Провайдер просил пускать остальное напрямую — "
        "Veblock намеренно это не поддерживает"
    )


def test_mode_row_only_when_mode_changes():
    proxy_all = RoutingSettings(mode=RoutingMode.PROXY_ALL)
    rows = import_rows(proxy_all, RoutingSettings(), name="", direct_default=False)
    assert ImportRow("Режим", "Весь трафик через прокси → Пользовательские списки") in rows
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="", direct_default=False)
    assert all(r.label != "Режим" for r in rows)


def test_rule_counts_are_declined():
    for count, value in ((2, "2 правила"), (5, "5 правил"), (11, "11 правил"), (21, "21 правило")):
        new = RoutingSettings(block_list=[f"h{i}.example" for i in range(count)])
        rows = import_rows(RoutingSettings(), new, name="", direct_default=False)
        block = next(r for r in rows if r.label == "Блокировать")
        assert block.value.startswith(value + ":")


def test_details_are_bounded():
    new = RoutingSettings(proxy_list=[f"h{i}.example" for i in range(30)])
    rows = import_rows(RoutingSettings(), new, name="", direct_default=False)
    proxy = next(r for r in rows if r.label == "Через прокси")
    assert len(proxy.details) == 11
    assert proxy.details[-1] == "и ещё 20"


def test_apply_keeps_a_backup_and_restore_returns_it(tmp_path):
    config = _legacy(tmp_path)
    config.routing.ru_direct = True
    apply_import(config, RoutingSettings(direct_list=["new.example"]), tmp_path)

    assert config.routing.direct_list == ["new.example"]
    assert config.routing.use_saved_lists
    assert config.routing.ru_direct  # то, чего нет в ссылке, импорт не трогает
    assert config.routing_backup.direct_list == ["old.example"]
    assert not config.routing_backup.use_saved_lists

    assert restore_backup(config)
    assert config.routing.direct_list == ["old.example"]
    assert not config.routing.use_saved_lists  # снова читаются файлы
    assert config.routing_backup is None
    assert not restore_backup(config)


def test_import_keeps_legacy_vpn_list(tmp_path):
    """VPN-список ссылка не переносит: после импорта он не должен пропасть."""
    (tmp_path / "vpn_list.txt").write_text("corp.example\n", encoding="utf-8")
    config = DataStore()
    apply_import(config, RoutingSettings(direct_list=["new.example"]), tmp_path)
    assert config.routing.vpn_list == ["corp.example"]


def test_second_import_keeps_only_the_latest_backup(tmp_path):
    config = DataStore()
    apply_import(config, RoutingSettings(direct_list=["a.example"]), tmp_path)
    apply_import(config, RoutingSettings(direct_list=["b.example"]), tmp_path)
    assert config.routing_backup.direct_list == ["a.example"]


def test_backup_survives_settings_round_trip(tmp_path):
    config = DataStore()
    apply_import(config, RoutingSettings(block_list=["ads.example"]), tmp_path)
    config.save(tmp_path / "settings.json")
    loaded = DataStore.load(tmp_path / "settings.json")
    assert isinstance(loaded.routing_backup, RoutingSettings)
    assert DataStore.load(tmp_path / "missing.json").routing_backup is None


def test_config_base_restores_pipe_optional_nested_settings():
    """`RoutingSettings | None` восстанавливается объектом, а не словарём."""
    loaded = DataStore.from_dict({"routing_backup": {"direct_list": ["a.example"]}})
    assert loaded.routing_backup == RoutingSettings(direct_list=["a.example"])
    assert DataStore.from_dict({"routing_backup": None}).routing_backup is None
