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


def test_the_fragment_settings_round_trip(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.fragment_row.set_active(True)
    dialog.fragment_packets_row.set_text("1-3")
    dialog.fragment_length_row.set_text("50-100")
    dialog.fragment_delay_row.set_text("5")
    dialog.save()

    assert config.tls_fragment.enabled is True
    assert config.tls_fragment.packets == "1-3"
    assert config.tls_fragment.length == "50-100"
    assert config.tls_fragment.delay == "5"

    reopened = make_dialog(config)
    assert reopened.fragment_row.get_active()
    assert reopened.fragment_length_row.get_text() == "50-100"


def test_invalid_fragment_values_fall_back_to_defaults(gtk_ready):
    """Невалидное значение ядро отвергло бы вместе со всем конфигом."""
    config = make_config()
    dialog = make_dialog(config)
    dialog.fragment_row.set_active(True)
    dialog.fragment_length_row.set_text("0-100")
    dialog.fragment_delay_row.set_text("soon")
    dialog.save()

    assert config.tls_fragment.length == "100-200"
    assert config.tls_fragment.delay == "10-20"


def test_disabled_fragmentation_dims_its_fields(gtk_ready):
    dialog = make_dialog()
    assert not dialog.fragment_length_row.get_sensitive()
    dialog.fragment_row.set_active(True)
    assert dialog.fragment_length_row.get_sensitive()


def test_the_mux_switch_round_trips(gtk_ready):
    config = make_config()
    dialog = make_dialog(config)
    dialog.mux_row.set_active(True)
    dialog.save()
    assert config.mux_default_on is True
    assert make_dialog(config).mux_row.get_active()
