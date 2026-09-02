"""Widget tests for the GTK4 settings dialog."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


def make_config():
    from src.db.data_store import DataStore

    config = DataStore()
    config.inbound_address = "127.0.0.1"
    config.inbound_socks_port = 2080
    config.proxy_mode = "system_proxy"
    config.log_level = "info"
    return config


def make_dialog(config=None):
    from src.ui.dialogs.settings import SettingsDialog

    return SettingsDialog(config or make_config())


def test_the_fields_are_loaded_from_the_config(gtk_ready):
    dialog = make_dialog()
    assert dialog.address_row.get_text() == "127.0.0.1"
    assert dialog.port_row.get_value() == 2080


def test_the_proxy_mode_is_preselected(gtk_ready):
    config = make_config()
    config.proxy_mode = "tun"
    assert make_dialog(config).selected_mode() == "tun"


def test_an_unknown_mode_falls_back_to_the_first(gtk_ready):
    """Конфиг мог прийти от другой версии — диалог не должен падать."""
    config = make_config()
    config.proxy_mode = "nonsense"
    assert make_dialog(config).mode_row.get_selected() == 0


def test_tun_rows_are_insensitive_in_system_mode(gtk_ready):
    assert not make_dialog().tun_name_row.get_sensitive()


def test_switching_to_tun_enables_its_rows(gtk_ready):
    dialog = make_dialog()
    dialog.select_mode("tun")
    assert dialog.tun_name_row.get_sensitive()
    assert dialog.tun_mtu_row.get_sensitive()


def test_saving_writes_the_config_back(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.address_row.set_text("0.0.0.0")
    dialog.port_row.set_value(3080)
    dialog.save()
    assert config.inbound_address == "0.0.0.0"
    assert config.inbound_socks_port == 3080


def test_saving_writes_the_selected_mode(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.select_mode("tun")
    dialog.save()
    assert config.proxy_mode == "tun"


def test_the_monitoring_interval_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.monitoring_row.set_active(True)
    dialog.interval_row.set_value(30)
    dialog.save()
    assert config.monitoring.enabled
    assert config.monitoring.check_interval_seconds == 30


def test_disabled_monitoring_dims_the_interval(gtk_ready):
    dialog = make_dialog()
    dialog.monitoring_row.set_active(False)
    assert not dialog.interval_row.get_sensitive()


def test_the_dns_provider_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.select_dns("cloudflare")
    dialog.save()
    assert config.dns.provider == "cloudflare"


def test_the_custom_dns_url_round_trips(gtk_ready):
    """Своё поле перекрывает выбранного провайдера — так было и в GTK3."""
    config = make_config()
    dialog = make_dialog(config)
    dialog.dns_url_row.set_text("  https://dns.example/dns-query  ")
    dialog.save()
    assert config.dns.custom_url == "https://dns.example/dns-query"


def test_an_empty_tun_name_falls_back_to_the_default(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.select_mode("tun")
    dialog.tun_name_row.set_text("")
    dialog.save()
    assert config.tun_name == "xray0"


def test_the_log_level_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.select_log_level("debug")
    dialog.save()
    assert config.log_level == "debug"


def test_the_dns_through_proxy_switch_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.dns_proxy_row.set_active(False)
    dialog.save()
    assert config.dns.use_proxy is False
