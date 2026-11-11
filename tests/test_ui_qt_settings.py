"""Qt-окно настроек: поля, проверка, автосохранение, подписки, «О программе»."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLineEdit, QMessageBox

from src.core.context import AppContext
from src.db.config import DnsProvider, ProxyMode, RoutingMode, RoutingSettings
from src.ui.controller import CONFIRM_URL_CHANGE
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.settings import SECTIONS, SettingsDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()


def _open(app) -> SettingsDialog:
    app.open_settings()
    dialog = app.current_dialog
    assert isinstance(dialog, SettingsDialog)
    return dialog


def _saved(app) -> dict:
    return json.loads((app.context.config_dir / "settings.json").read_text(encoding="utf-8"))


def test_save_failure_is_not_reported_as_success(app, monkeypatch):
    dialog = _open(app)
    monkeypatch.setattr(app.context, "save_config", lambda: False)
    dialog.interval_spin.setValue(27)
    assert dialog.status.text() == "Ожидание сохранения…"
    assert not dialog.save()
    assert "Не удалось сохранить" in dialog.status.text()
    assert dialog.status.property("error") is True


def test_proxy_mode_hides_tun_fields_without_losing_values(app):
    dialog = _open(app)
    dialog.mode_combo.select(ProxyMode.TUN)
    dialog.tun_name_edit.setText("synthetic-tun")
    dialog.mode_combo.select(ProxyMode.SYSTEM_PROXY)
    assert dialog.tun_name_edit.isHidden()
    assert dialog.tun_mtu_spin.isHidden()
    assert dialog.save()
    dialog.mode_combo.select(ProxyMode.TUN)
    assert not dialog.tun_name_edit.isHidden()
    assert dialog.tun_name_edit.text() == "synthetic-tun"


def test_settings_action_opens_the_settings_window(app):
    app.actions["settings"].trigger()

    assert isinstance(app.current_dialog, SettingsDialog)


def test_url_change_question_opens_over_settings(app):
    app.actions["settings"].trigger()
    settings = app.current_dialog
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: confirmed.append(1)
    )

    box = settings.findChildren(QMessageBox)[-1]
    assert app.current_dialog is settings
    next(b for b in box.buttons() if b.text() == "Сменить").click()
    assert confirmed == [1]


# --- поля и сохранение ---


def test_sections_switch_pages(app):
    dialog = _open(app)

    assert [dialog.sections.item(i).text() for i in range(dialog.sections.count())] == list(
        SECTIONS
    )
    dialog.show_section("DNS")
    assert dialog.pages.currentIndex() == 2


def test_fields_come_from_the_config(app):
    config = app.context.config
    config.inbound_address = "127.0.0.2"
    config.proxy_mode = ProxyMode.SYSTEM_PROXY
    config.close_to_tray = False

    dialog = _open(app)

    assert dialog.address_edit.text() == "127.0.0.2"
    assert dialog.mode_combo.selected() == ProxyMode.SYSTEM_PROXY
    assert not dialog.tun_name_edit.isEnabled()
    assert not dialog.close_to_tray_check.isChecked()


def test_numeric_fields_have_room_for_their_values(app):
    dialog = _open(app)
    process_events()
    for spin in (dialog.port_spin, dialog.tun_mtu_spin):
        editor = spin.findChild(QLineEdit)
        assert editor.isVisible()
        assert editor.width() > editor.fontMetrics().horizontalAdvance(editor.text())


def test_save_writes_the_config_and_reaches_the_controller(app):
    dialog = _open(app)
    dialog.dns_combo.select(DnsProvider.ALL[-1])
    dialog.interval_spin.setValue(30)
    dialog.close_to_tray_check.setChecked(False)

    assert dialog.save()

    config = app.context.config
    assert config.dns.provider == DnsProvider.ALL[-1]
    assert config.monitoring.check_interval_seconds == 30
    assert config.close_to_tray is False
    assert _saved(app)["monitoring"]["check_interval_seconds"] == 30


def test_invalid_field_is_marked_and_nothing_changes(app):
    dialog = _open(app)
    dialog.address_edit.setText("не адрес")
    dialog.interval_spin.setValue(42)

    assert not dialog.save()

    assert dialog.address_edit.property("error") is True
    assert dialog.address_edit.toolTip() == "Введите IP-адрес или localhost"
    assert dialog.status.text().startswith("Исправьте настройки: ")
    assert app.context.config.monitoring.check_interval_seconds != 42

    dialog.address_edit.setText("127.0.0.1")
    assert dialog.save()
    assert dialog.address_edit.property("error") is False
    assert dialog.status.text().startswith("Изменения сохранены")


def test_edits_autosave_and_closing_flushes(app):
    dialog = _open(app)

    dialog.interval_spin.setValue(25)
    assert dialog.autosave.pending
    dialog.reject()

    assert app.context.config.monitoring.check_interval_seconds == 25
    assert _saved(app)["monitoring"]["check_interval_seconds"] == 25


def test_monitoring_switch_dims_failover(app):
    dialog = _open(app)

    dialog.monitoring_check.setChecked(False)
    assert not dialog.interval_spin.isEnabled()
    assert not dialog.failover_check.isEnabled()
    dialog.monitoring_check.setChecked(True)
    dialog.failover_check.setChecked(False)
    assert not dialog.failover_threshold_spin.isEnabled()


def test_fragment_fields_follow_the_switch(app):
    dialog = _open(app)

    dialog.fragment_check.setChecked(False)
    assert not dialog.fragment_length_edit.isEnabled()
    dialog.fragment_check.setChecked(True)
    assert dialog.fragment_length_edit.isEnabled()


def test_removed_request_settings_are_preserved(app):
    config = app.context.config
    config.user_agent = "SyntheticClient/1.0"
    config.sub_send_device_info = True
    config.sub_hwid = "synthetic-device"
    config.sub_source_exceptions = ["http://example.org/sub"]
    config.sub_insecure = True
    dialog = _open(app)

    assert not hasattr(dialog, "user_agent_edit")
    dialog.interval_spin.setValue(27)
    assert dialog.save()

    saved = _saved(app)
    assert saved["user_agent"] == "SyntheticClient/1.0"
    assert saved["sub_send_device_info"] is True
    assert saved["sub_hwid"] == "synthetic-device"
    assert saved["sub_source_exceptions"] == ["http://example.org/sub"]
    assert saved["sub_insecure"] is True


def test_missing_tun_rights_are_shown(app, monkeypatch):
    monkeypatch.setattr("src.sys.tun_access.tun_problems", lambda _xray: ["нет правила sudoers"])
    app.context.config.proxy_mode = ProxyMode.TUN

    dialog = _open(app)

    wait_until(lambda: "нет правила sudoers" in dialog.tun_access_label.text())
    assert "нет правила sudoers" in dialog.tun_access_label.text()
    dialog.mode_combo.select(ProxyMode.SYSTEM_PROXY)
    assert dialog.tun_access_label.isHidden()


@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_theme_applies_at_once(app, monkeypatch, theme):
    applied = []
    monkeypatch.setattr("src.ui.qt.dialogs.settings.apply_theme", applied.append)
    dialog = _open(app)

    dialog.theme_combo.select("light" if theme == "dark" else "dark")
    applied.clear()
    dialog.theme_combo.select(theme)

    assert applied == [theme]
    dialog.save()
    assert app.context.config.theme == theme


# --- подписки ---


def _subscription(app, name="Провайдер", **fields):
    group = app.context.profiles.add_group(name, is_subscription=True)
    group.subscription_url = "https://sub.example.org/s"
    for key, value in fields.items():
        setattr(group, key, value)
    return group


def test_subscriptions_are_listed_with_details(app):
    _subscription(
        app,
        sub_user_info="upload=0; download=1073741824; total=2147483648; expire=1000000000",
    )
    app.context.profiles.add_group("Обычная")

    dialog = _open(app)
    tree = dialog.subscriptions.tree

    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item.text(0) == "Провайдер"
    assert "истекла" in item.text(3)
    assert item.toolTip(0) == "https://sub.example.org/s"


def test_empty_list_shows_a_hint(app):
    dialog = _open(app)

    assert dialog.subscriptions.tree.isHidden()
    assert not dialog.subscriptions.empty_label.isHidden()


def test_buttons_follow_the_selection_and_menu_lists_provider_links(app):
    _subscription(app, sub_web_page_url="https://provider.example/account", sub_announce="Тех")
    dialog = _open(app)
    page = dialog.subscriptions
    assert not page.edit_button.isEnabled()

    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    assert page.edit_button.isEnabled() and page.more_button.isEnabled()
    assert page.menu_labels() == [
        "Обновить",
        "Изменить…",
        "Страница подписки",
        "Объявление провайдера",
        "Удалить",
    ]


def test_update_goes_to_the_controller(app, monkeypatch):
    group = _subscription(app)
    seen = []
    monkeypatch.setattr(app.controller, "update_subscription", seen.append)
    dialog = _open(app)
    dialog.subscriptions.tree.setCurrentItem(dialog.subscriptions.tree.topLevelItem(0))

    dialog.subscriptions.update_button.click()

    assert seen == [group.id]


def test_edit_opens_over_settings_and_refreshes_the_list(app):
    group = _subscription(app)
    dialog = _open(app)
    page = dialog.subscriptions
    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    page.edit_button.click()

    form = next(w for w in dialog.findChildren(SubscriptionDialog))
    assert app.current_dialog is dialog  # слот занят настройками, форма поверх них
    form.name_edit.setText("Новое имя")
    form.confirm_button.click()
    process_events()
    assert group.name == "Новое имя"
    assert page.tree.topLevelItem(0).text(0) == "Новое имя"


def test_delete_asks_over_settings(app):
    group = _subscription(app)
    dialog = _open(app)
    page = dialog.subscriptions
    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    page.delete_button.click()

    box = dialog.findChildren(QMessageBox)[-1]
    next(b for b in box.buttons() if b.text() == "Удалить").click()
    process_events()
    assert app.context.profiles.get_group(group.id) is None
    assert page.tree.topLevelItemCount() == 0


def test_add_opens_the_subscription_form_over_settings(app):
    dialog = _open(app)

    dialog.subscriptions.add_button.click()

    assert dialog.findChildren(SubscriptionDialog)


# --- о программе ---


def test_core_update_check_updates_the_row(app):
    from src.core.core_update import KnownReleases

    dialog = _open(app)
    about = dialog.about
    about.fetch_releases = lambda: KnownReleases(stable="26.3.27", prerelease="26.9.30")

    about.check_core_update()
    about.core_update_thread.join(5)
    wait_until(lambda: about.core_update_button.isEnabled())

    assert app.context.config.core_update_checked_at > 0
    assert about.core_update_label.text() != "Проверяю…"


def test_failed_core_check_is_reported(app):
    def offline():
        raise OSError("нет сети")

    dialog = _open(app)
    about = dialog.about
    about.fetch_releases = offline

    about.check_core_update()
    about.core_update_thread.join(5)
    wait_until(lambda: about.core_update_button.isEnabled())

    assert about.core_update_label.text() == "Не удалось проверить обновления"


def test_app_update_check_without_releases(app):
    dialog = _open(app)
    about = dialog.about
    about.fetch_app_releases = list

    about.check_app_update()
    about.app_update_thread.join(5)
    wait_until(lambda: about.app_check_button.isEnabled())

    assert about.app_update_label.text() == "Новых версий нет"


RELEASE_PAGE = "https://github.com/vebulogmetra/veblock/releases/tag/windows-v0.19.0"
UNAVAILABLE = "Доступна версия v0.19.0. Установщик недоступен, обновите вручную со страницы проекта"


def _installable(config):
    config.app_update_target = "v0.19.0"
    config.app_update_url = RELEASE_PAGE
    config.app_update_has_asset = True
    config.app_update_asset_url = (
        "https://github.com/vebulogmetra/veblock/releases/download/windows-v0.19.0/"
        "veblock-0.19.0-windows-x64-setup.exe"
    )
    config.app_update_asset_size = 3
    config.app_update_asset_digest = "sha256:" + "ab" * 32


def test_about_offers_the_release_page_without_self_update(app):
    _installable(app.context.config)

    about = _open(app).about

    assert about.app_update_button.text() == "Открыть релиз"
    assert about.app_update_button.isEnabled()
    assert about.app_update_label.text() == "Доступна версия v0.19.0"


def test_about_offers_install_when_self_update_is_possible(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    seen = []
    app._handlers["install-app-update"] = lambda _target: seen.append(1)

    about = _open(app).about
    about.app_update_button.click()

    assert about.app_update_button.text() == "Обновить…"
    assert seen == [1]


def test_about_disables_install_without_a_digest(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    app.context.config.app_update_asset_digest = ""

    about = _open(app).about

    assert not about.app_update_button.isEnabled()
    assert about.app_update_label.text() == UNAVAILABLE


def test_about_shows_install_progress_from_the_controller(app, monkeypatch):
    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    _installable(app.context.config)
    about = _open(app).about

    app.controller._set_app_update_status("Загрузка… 42 %", busy=True)

    assert about.app_update_label.text() == "Загрузка… 42 %"
    assert not about.app_update_button.isEnabled()


def test_manual_check_reports_a_release_without_installer(app, monkeypatch):
    """Ручная проверка идёт с настоящей версией приложения: релиз заведомо новее."""
    from src.core import platform_info
    from tests.test_core_app_update import WINDOWS_ASSET

    monkeypatch.setattr(app.controller, "can_self_update", lambda: True)
    about = _open(app).about
    # После открытия окна: иначе контекст искал бы ядро по путям Windows.
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    about.fetch_app_releases = lambda: [
        {
            "tag_name": "windows-v99.0.0",
            "html_url": "https://github.com/vebulogmetra/veblock/releases/tag/windows-v99.0.0",
            "assets": [dict(WINDOWS_ASSET, digest="")],
        }
    ]

    about.check_app_update()
    about.app_update_thread.join(5)
    wait_until(lambda: about.app_check_button.isEnabled())

    assert about.app_update_label.text() == UNAVAILABLE.replace("v0.19.0", "v99.0.0")
    assert not about.app_update_button.isEnabled()


def test_routing_page_round_trips_the_shared_rules(app):
    dialog = _open(app)
    dialog.show_section("Маршрутизация")
    assert dialog.pages.currentIndex() == 3
    dialog.routing.mode_combo.select(RoutingMode.CUSTOM)
    dialog.routing.lists["proxy"].setPlainText("a.com\nb.com")

    assert dialog.save()

    assert app.context.config.routing.proxy_list == ["a.com", "b.com"]
    assert app.context.config.routing.use_saved_lists is True
    assert _saved(app)["routing"]["proxy_list"] == ["a.com", "b.com"]


def test_untouched_routing_page_keeps_legacy_list_files(app):
    (app.context.config_dir / "direct_list.txt").write_text("old.example\n", encoding="utf-8")
    dialog = _open(app)
    assert dialog.routing.lists["direct"].toPlainText() == "old.example"
    dialog.interval_spin.setValue(27)

    assert dialog.save()

    assert app.context.config.routing.use_saved_lists is False


def test_bad_routing_entry_blocks_saving(app):
    dialog = _open(app)
    dialog.routing.mode_combo.select(RoutingMode.CUSTOM)
    dialog.routing.lists["direct"].setPlainText("http://user:pw@x.com")
    assert not dialog.save()
    assert dialog.routing.lists["direct"].property("error") is True
    assert dialog.status.property("error") is True
    assert app.context.config.routing.direct_list == []


def test_restore_routing_row_follows_the_backup_on_the_routing_page(app):
    dialog = _open(app)
    assert dialog.routing_extra_group.isHidden()
    assert not dialog.routing_extra.isRowVisible(dialog.restore_routing_row)

    app.context.config.routing_backup = RoutingSettings()
    app.context.config.routing.proxy_list = ["imported.example"]
    app.context.config.routing.use_saved_lists = True
    app.controller.sync_restore_routing()

    assert not dialog.routing_extra_group.isHidden()
    assert dialog.routing_extra.isRowVisible(dialog.restore_routing_row)
    assert dialog.routing.lists["proxy"].toPlainText() == "imported.example"
    assert not dialog.autosave.pending
    assert not hasattr(dialog.about, "restore_routing_row")


def test_refresh_keeps_unsaved_routing_edits(app):
    dialog = _open(app)
    dialog.routing.mode_combo.select(RoutingMode.CUSTOM)
    dialog.routing.lists["proxy"].setPlainText("typing.example")

    dialog.refresh()

    assert dialog.routing.lists["proxy"].toPlainText() == "typing.example"


def test_clear_logs_asks_first(app, monkeypatch):
    cleared = []
    monkeypatch.setattr(
        app.context.log_manager, "clear_all_logs", lambda: cleared.append(1) or (3, 0)
    )
    dialog = _open(app)
    dialog.about._on_clear_logs()

    box = dialog.findChildren(QMessageBox)[-1]
    next(b for b in box.buttons() if b.text() == "Очистить").click()

    wait_until(lambda: dialog.about.clear_logs_label.text() == "Очищено файлов: 3")
    assert cleared == [1]


def test_an_update_through_the_fallback_is_marked(app):
    _subscription(app, sub_via_fallback=True)

    dialog = _open(app)

    assert "Обновлено через запасной адрес" in dialog.subscriptions.tree.topLevelItem(0).text(3)


def test_a_normal_update_has_no_fallback_mark(app):
    _subscription(app)

    dialog = _open(app)

    assert "запасной" not in dialog.subscriptions.tree.topLevelItem(0).text(3)


def test_kill_switch_follows_the_tun_mode(app):
    app.context.config.proxy_mode = ProxyMode.SYSTEM_PROXY

    dialog = _open(app)

    assert not dialog.kill_switch_check.isEnabled()
    dialog.mode_combo.select(ProxyMode.TUN)
    assert dialog.kill_switch_check.isEnabled()


def test_kill_switch_round_trips(app):
    app.context.config.proxy_mode = ProxyMode.TUN
    dialog = _open(app)

    dialog.kill_switch_check.setChecked(True)
    dialog.save()

    assert app.context.config.tun_kill_switch is True
    assert _saved(app)["tun_kill_switch"] is True


def test_kill_switch_is_hidden_where_it_does_not_work(app, monkeypatch):
    monkeypatch.setattr("src.ui.qt.dialogs.settings.kill_switch_available", lambda: False)

    dialog = _open(app)

    assert dialog.kill_switch_check.isHidden()
