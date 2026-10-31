"""Qt-окно настроек: поля, проверка, автосохранение, подписки, «О программе»."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLineEdit, QMessageBox

from src.core.context import AppContext
from src.db.config import DnsProvider, ProxyMode, RoutingSettings
from src.db.data_store import LEGACY_USER_AGENT
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
    config.user_agent = LEGACY_USER_AGENT
    config.close_to_tray = False

    dialog = _open(app)

    assert dialog.address_edit.text() == "127.0.0.2"
    assert dialog.mode_combo.selected() == ProxyMode.SYSTEM_PROXY
    assert not dialog.tun_name_edit.isEnabled()
    # Старое значение по умолчанию показывается как «не задано».
    assert dialog.user_agent_edit.text() == ""
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
    assert dialog.status.isHidden()


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


def test_device_info_creates_the_hwid(app):
    dialog = _open(app)

    dialog.device_info_check.setChecked(True)
    dialog.save()

    assert app.context.config.sub_hwid


def test_missing_tun_rights_are_shown(app, monkeypatch):
    monkeypatch.setattr("src.sys.tun_access.tun_problems", lambda _xray: ["нет правила sudoers"])
    app.context.config.proxy_mode = ProxyMode.TUN

    dialog = _open(app)

    wait_until(lambda: not dialog.tun_access_label.isHidden())
    assert "нет правила sudoers" in dialog.tun_access_label.text()
    dialog.mode_combo.select(ProxyMode.SYSTEM_PROXY)
    assert dialog.tun_access_label.isHidden()


def test_theme_applies_at_once(app, monkeypatch):
    applied = []
    monkeypatch.setattr("src.ui.qt.dialogs.settings.apply_theme", applied.append)
    dialog = _open(app)

    dialog.theme_combo.select("dark")

    assert applied == ["dark"]
    dialog.save()
    assert app.context.config.theme == "dark"


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


def test_restore_routing_row_follows_the_backup(app):
    dialog = _open(app)
    about = dialog.about
    assert not about._maintenance.isRowVisible(about.restore_routing_row)

    app.context.config.routing_backup = RoutingSettings()
    app.controller.sync_restore_routing()

    assert about._maintenance.isRowVisible(about.restore_routing_row)


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
