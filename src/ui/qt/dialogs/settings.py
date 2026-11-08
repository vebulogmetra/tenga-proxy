"""Окно настроек: разделы слева, страница справа, как в «Параметрах» Windows.

Кнопки «Сохранить» нет, как и в GTK: правки сохраняются через полсекунды
после последней и при закрытии окна. Проверка — `validate_settings`, общая
с GTK; поле с ошибкой подсвечивается, настройки не меняются, пока ошибка
не исправлена.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.core.config import get_asset_path
from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
from src.sys import tun_access
from src.ui.logic.appearance import ACCENT, THEME_LABELS, THEMES, normalize_theme
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.platform_texts import (
    KILL_SWITCH_HINT,
    KILL_SWITCH_LABEL,
    kill_switch_available,
)
from src.ui.logic.settings_form import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_TUN_NAME,
    LOG_LEVELS,
    SAVE_FAILED,
    SAVE_IDLE,
    SAVE_PENDING,
    SETTINGS_SECTIONS,
    invalid_text,
    save_status_text,
    validate_settings,
)
from src.ui.qt.dialogs.base import Debounce, FormStyle, KeyedCombo, mark_error, watch
from src.ui.qt.theme import apply_theme

if TYPE_CHECKING:
    from src.ui.qt.dialogs.settings_pages import AboutPage, SubscriptionsPage

SECTIONS = tuple(title for _key, title, _icon in SETTINGS_SECTIONS)

SETTINGS_STYLE = """
QDialog QWidget { font-size: 11pt; }
QCheckBox::indicator { width: 18px; height: 18px; }
QCheckBox#trayToggle::indicator { width: 36px; height: 20px; image: url("TOGGLE_OFF"); }
QCheckBox#trayToggle::indicator:checked { image: url("TOGGLE_ON"); }
QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }
QGroupBox {
    border: 1px solid palette(mid);
    border-radius: 8px;
    margin-top: 20px;
    padding: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0;
    font-weight: 600;
    font-size: 12pt;
}
QLabel#settingsTitle { font-size: 20pt; font-weight: 600; padding: 8px 16px; }
QListWidget#settingsSections { border: none; background: transparent; outline: none; }
QListWidget#settingsSections::item { padding: 10px 12px; border-radius: 8px; }
QListWidget#settingsSections::item:hover { background: palette(alternate-base); }
QListWidget#settingsSections::item:selected {
    background: palette(alternate-base);
    color: palette(text);
    border-left: 3px solid ACCENT_COLOR;
}
QListWidget#settingsSections::item:focus { border: 1px solid palette(highlight); }
"""

SETTINGS_STYLE = (
    SETTINGS_STYLE.replace("ACCENT_COLOR", ACCENT)
    .replace("TOGGLE_OFF", get_asset_path("icons/ui/toggle-off.svg").as_posix())
    .replace("TOGGLE_ON", get_asset_path("icons/ui/toggle-on.svg").as_posix())
)

# Поле проверки (`validate_settings`) → атрибут виджета.
ERROR_FIELDS = {
    "address": "address_edit",
    "tun_name": "tun_name_edit",
    "dns_url": "dns_url_edit",
    "dns_additional": "dns_additional_edit",
    "fragment_packets": "fragment_packets_edit",
    "fragment_length": "fragment_length_edit",
    "fragment_delay": "fragment_delay_edit",
}


def spin(low: int, high: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    return box


def check(text: str, hint: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(hint)
    return box


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setEnabled(False)  # приглушённый цвет системной палитры
    return label


def page(*groups: QWidget) -> QScrollArea:
    """Страница раздела: группы сверху вниз, прокрутка при нехватке места."""
    body = QWidget()
    column = QVBoxLayout(body)
    column.setContentsMargins(16, 4, 16, 16)
    column.setSpacing(10)
    for group in groups:
        for form in group.findChildren(QFormLayout):
            form.setContentsMargins(0, 8, 0, 0)
            form.setVerticalSpacing(8)
            form.setHorizontalSpacing(20)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        column.addWidget(group)
    column.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(body)
    return scroll


class SettingsDialog(QDialog):
    settings_saved = Signal()

    def __init__(
        self,
        app,
        *,
        dispatch: Callable[..., object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки — Monoliten")
        self.setModal(True)
        self.resize(960, 700)
        self.setMinimumSize(640, 440)
        self._form_style = FormStyle(self, SETTINGS_STYLE)
        self._app = app
        self._context = app.context
        self._config = app.context.config
        self._dispatch = dispatch
        self.validation_errors: dict[str, str] = {}
        # None — проверка прав для TUN ещё не запускалась.
        self._tun_problems: list[str] | None = None
        self.tun_access_thread = None

        from src.ui.qt.dialogs.settings_pages import AboutPage, SubscriptionsPage

        self.subscriptions: SubscriptionsPage = SubscriptionsPage(self)
        self.about: AboutPage = AboutPage(self)

        self.sections = QListWidget()
        self.sections.setObjectName("settingsSections")
        self.sections.addItems(list(SECTIONS))
        for row, (_key, _title, name) in enumerate(SETTINGS_SECTIONS):
            self.sections.item(row).setIcon(QIcon(str(get_asset_path(f"icons/ui/{name}.svg"))))
        self.sections.setFixedWidth(200)
        self.pages = QStackedWidget()
        for widget in (
            self._general_page(),
            self._monitoring_page(),
            self._dns_page(),
            self._routing_page(),
            self._bypass_page(),
            page(self.subscriptions),
            page(self.about),
        ):
            self.pages.addWidget(widget)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(0)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("error", False)
        self.status.setText(SAVE_IDLE)
        buttons = QDialogButtonBox()
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        navigation = QVBoxLayout()
        navigation.addWidget(QLabel("Настройки"))
        navigation.addWidget(self.sections, 1)
        body.addLayout(navigation)
        content = QVBoxLayout()
        self.section_title = QLabel(SECTIONS[0])
        self.section_title.setObjectName("settingsTitle")
        self.sections.currentRowChanged.connect(
            lambda row: self.section_title.setText(SECTIONS[row]) if row >= 0 else None
        )
        content.addWidget(self.section_title)
        content.addWidget(self.pages, 1)
        body.addLayout(content, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(buttons)
        layout.addLayout(footer)

        self._loading = False
        self._load()
        self.autosave = Debounce(self.save, parent=self)
        watch(self._fields(), self._queue_save)
        self.finished.connect(lambda _result: self.autosave.flush())

    def _queue_save(self) -> None:
        if self._loading:
            return
        self.status.setProperty("error", False)
        self.status.setText(SAVE_PENDING)
        mark_error(self.status, None)
        self.status.show()
        self.autosave.queue()

    # --- страницы ---

    def _general_page(self) -> QWidget:
        inbound = QGroupBox("Входящее соединение")
        form = QFormLayout(inbound)
        form.addRow(hint("Локальные порты SOCKS и HTTP"))
        self.address_edit = QLineEdit()
        form.addRow("Адрес", self.address_edit)
        self.port_spin = spin(1024, 65534)
        self.port_spin.setToolTip("HTTP занимает следующий порт")
        form.addRow("Порт SOCKS", self.port_spin)

        runtime = QGroupBox("Режим работы")
        form = QFormLayout(runtime)
        self.mode_combo = KeyedCombo(ProxyMode.ALL, ProxyMode.LABELS)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Режим", self.mode_combo)
        self.tun_name_edit = QLineEdit()
        form.addRow("Имя интерфейса TUN", self.tun_name_edit)
        self.tun_mtu_spin = spin(576, 9000)
        form.addRow("MTU", self.tun_mtu_spin)
        self.kill_switch_check = check(KILL_SWITCH_LABEL, KILL_SWITCH_HINT)
        self.kill_switch_check.setVisible(kill_switch_available())
        form.addRow(self.kill_switch_check)
        self.tun_access_label = QLabel()
        self.tun_access_label.setWordWrap(True)
        self.tun_access_label.setProperty("error", True)
        # Подсказка с командой для исправления: её копируют в терминал.
        self.tun_access_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tun_access_label.hide()
        form.addRow(self.tun_access_label)

        window = QGroupBox("Окно")
        form = QFormLayout(window)
        self.theme_combo = KeyedCombo(THEMES, THEME_LABELS)
        # Тема меняется сразу, чтобы выбор было видно; в настройки попадает
        # вместе с остальными полями.
        self.theme_combo.currentIndexChanged.connect(
            lambda _index: apply_theme(self.theme_combo.selected())
        )
        form.addRow("Тема", self.theme_combo)
        self.close_to_tray_check = check(
            "Сворачивать в трей при закрытии окна",
            "Без трея закрытие окна всегда завершает приложение",
        )
        self.close_to_tray_check.setObjectName("trayToggle")
        form.addRow(self.close_to_tray_check)

        logs = QGroupBox("Журнал")
        form = QFormLayout(logs)
        self.log_level_combo = KeyedCombo(LOG_LEVELS, {level: level for level in LOG_LEVELS})
        form.addRow("Уровень подробности", self.log_level_combo)
        for group in (inbound, runtime, window, logs):
            form = group.layout()
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                if item is not None:
                    item.widget().setMinimumWidth(160)
        return page(runtime, inbound, window, logs)

    def _monitoring_page(self) -> QWidget:
        monitoring = QGroupBox("Проверка соединения")
        form = QFormLayout(monitoring)
        form.addRow(hint("Периодический опрос прокси и VPN"))
        self.monitoring_check = check("Включить мониторинг")
        self.monitoring_check.toggled.connect(self._sync_monitoring)
        form.addRow(self.monitoring_check)
        self.interval_spin = spin(5, 60, " с")
        self.interval_spin.setToolTip("Секунд между проверками")
        form.addRow("Интервал", self.interval_spin)

        failover = QGroupBox("Автопереключение")
        form = QFormLayout(failover)
        form.addRow(hint("Если сервер перестал отвечать, подключается другой сервер той же группы"))
        self.failover_check = check("Переключаться автоматически")
        self.failover_check.toggled.connect(self._sync_monitoring)
        form.addRow(self.failover_check)
        self.failover_threshold_spin = spin(1, 10)
        self.failover_threshold_spin.setToolTip("Неудачных проверок подряд")
        form.addRow("Порог", self.failover_threshold_spin)
        return page(monitoring, failover)

    def _dns_page(self) -> QWidget:
        provider = QGroupBox("Провайдер")
        form = QFormLayout(provider)
        self.dns_combo = KeyedCombo(DnsProvider.ALL, DnsProvider.LABELS)
        form.addRow("DNS-сервер", self.dns_combo)

        custom = QGroupBox("Свой адрес")
        form = QFormLayout(custom)
        form.addRow(
            hint(
                "Непустое поле перекрывает выбранного провайдера. "
                "Примеры: 8.8.8.8, https://dns.google/dns-query"
            )
        )
        self.dns_url_edit = QLineEdit()
        form.addRow("Адрес DNS", self.dns_url_edit)
        self.dns_additional_edit = QLineEdit()
        form.addRow("Дополнительный DNS", self.dns_additional_edit)

        options = QGroupBox("Опции")
        form = QFormLayout(options)
        self.dns_proxy_check = check(
            "Запросы через прокси", "Помогает обойти блокировки на уровне DNS"
        )
        form.addRow(self.dns_proxy_check)
        self.dns_intercept_check = check(
            "Перехватывать DNS приложений",
            "Режим TUN: запросы приложений обрабатывает ядро — "
            "действуют списки маршрутизации и блокировка",
        )
        form.addRow(self.dns_intercept_check)
        return page(provider, custom, options)

    def _routing_page(self) -> QWidget:
        from src.ui.logic.routing_form import GLOBAL_PAGE_HINT, VPN_LIST_HINT
        from src.ui.qt.widgets.routing_form import RoutingForm

        self.routing = RoutingForm(vpn_hint=VPN_LIST_HINT)

        extra = self.routing_extra_group = QGroupBox("Дополнительно")
        self.routing_extra = QFormLayout(extra)
        # Без подтверждения, как в Android: откат возвращает только то, что
        # пользователь сам только что заменил импортом.
        self.restore_routing_button = QPushButton("Вернуть")
        self.restore_routing_button.setMinimumWidth(100)
        self.restore_routing_button.clicked.connect(
            lambda: self._app.activate_action("restore-routing")
        )
        label = QLabel("Режим и списки до последнего импорта")
        label.setWordWrap(True)
        self.restore_routing_row = QWidget()
        row = QHBoxLayout(self.restore_routing_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label, 1)
        row.addWidget(self.restore_routing_button)
        self.routing_extra.addRow("Маршрутизация до импорта", self.restore_routing_row)
        self.routing_extra_group.setVisible(self._config.routing_backup is not None)
        self.routing_extra.setRowVisible(
            self.restore_routing_row, self._config.routing_backup is not None
        )
        return page(hint(GLOBAL_PAGE_HINT), self.routing, extra)

    def _shared_routing(self):
        from src.ui.logic.routing_import import effective_routing

        return effective_routing(self._config.routing, self._context.config_dir)

    def _load_routing(self) -> None:
        from src.ui.logic.routing_form import form_values

        shared = self._shared_routing()
        self._loading = True
        try:
            self.routing.load(shared)
        finally:
            self._loading = False
        # Что показано: без правок форма общие правила не пишет, и старая
        # установка продолжает читать списки из своих файлов.
        self._routing_loaded = form_values(shared)

    def _bypass_page(self) -> QWidget:
        fragment = QGroupBox("Фрагментация TLS")
        form = QFormLayout(fragment)
        form.addRow(
            hint(
                "Делит начало TLS-соединения на части, чтобы фильтр не разобрал имя "
                "сервера. Действует на серверы с TLS и Reality. Вступает в силу после "
                "переподключения."
            )
        )
        self.fragment_check = check("Включить фрагментацию")
        self.fragment_check.toggled.connect(self._sync_fragment)
        form.addRow(self.fragment_check)
        self.fragment_packets_edit = QLineEdit()
        self.fragment_packets_edit.setPlaceholderText("tlshello или номера, 1-3")
        form.addRow("Пакеты", self.fragment_packets_edit)
        self.fragment_length_edit = QLineEdit()
        self.fragment_length_edit.setPlaceholderText("100-200")
        form.addRow("Размер фрагмента, байт", self.fragment_length_edit)
        self.fragment_delay_edit = QLineEdit()
        self.fragment_delay_edit.setPlaceholderText("10-20")
        form.addRow("Пауза между фрагментами, мс", self.fragment_delay_edit)

        mux = QGroupBox("Мультиплексирование")
        form = QFormLayout(mux)
        self.mux_check = check(
            "Включить mux",
            "Несколько потоков в одном соединении. Только VLESS и Trojan, кроме XHTTP и Vision",
        )
        form.addRow(self.mux_check)
        return page(fragment, mux)

    def _fields(self) -> list[QWidget]:
        return [
            self.address_edit,
            self.port_spin,
            self.mode_combo,
            self.tun_name_edit,
            self.tun_mtu_spin,
            self.kill_switch_check,
            self.theme_combo,
            self.close_to_tray_check,
            self.log_level_combo,
            self.monitoring_check,
            self.interval_spin,
            self.failover_check,
            self.failover_threshold_spin,
            self.dns_combo,
            self.dns_url_edit,
            self.dns_additional_edit,
            self.dns_proxy_check,
            self.dns_intercept_check,
            self.fragment_check,
            self.fragment_packets_edit,
            self.fragment_length_edit,
            self.fragment_delay_edit,
            self.mux_check,
            *self.routing.fields(),
            *self.about.fields(),
        ]

    # --- состояние ---

    def run(self, fn, on_done=None, on_error=None, *, name: str):
        """Фоновая задача; ответ доставляется, только пока окно живо."""

        def alive(callback):
            if callback is None:
                return None
            return lambda value: callback(value) if isValid(self) else None

        return run_in_background(
            fn, alive(on_done), alive(on_error), dispatch=self._dispatch, name=name
        )

    def _sync_mode(self) -> None:
        tun = self.mode_combo.selected() == ProxyMode.TUN
        form = self.mode_combo.parentWidget().layout()
        form.setRowVisible(self.tun_name_edit, tun)
        form.setRowVisible(self.tun_mtu_spin, tun)
        self.kill_switch_check.setVisible(tun and kill_switch_available())
        self.tun_name_edit.setEnabled(tun)
        self.tun_mtu_spin.setEnabled(tun)
        self.kill_switch_check.setEnabled(tun)
        if tun and self._tun_problems is None:
            self._check_tun_access()
        self._sync_tun_access()

    def _check_tun_access(self) -> None:
        # sudo и служба отвечают не мгновенно: открытие окна ждать не должно.
        from src.core.config import find_xray_binary

        self._tun_problems = []
        self._tun_check_pending = True
        self._sync_tun_access()
        self.tun_access_thread = self.run(
            lambda: tun_access.tun_problems(find_xray_binary()),
            self._on_tun_access_checked,
            lambda _error: self._on_tun_access_checked(["Не удалось проверить доступ к TUN"]),
            name="tenga-tun-access",
        )

    def _on_tun_access_checked(self, problems: list[str]) -> None:
        self._tun_check_pending = False
        self._tun_problems = list(problems)
        self._sync_tun_access()

    def _sync_tun_access(self) -> None:
        problems = self._tun_problems or []
        pending = getattr(self, "_tun_check_pending", False)
        text = (
            "Проверка доступа к TUN…"
            if pending
            else "TUN не заработает:\n" + "\n".join(problems)
            if problems
            else "Предварительная проверка доступа к TUN пройдена"
        )
        self.tun_access_label.setText(text)
        mark_error(self.tun_access_label, text if problems else None)
        self.tun_access_label.setVisible(self.mode_combo.selected() == ProxyMode.TUN)

    def _sync_monitoring(self) -> None:
        monitoring = self.monitoring_check.isChecked()
        self.interval_spin.setEnabled(monitoring)
        # Без мониторинга проверок нет — переключаться не по чему.
        self.failover_check.setEnabled(monitoring)
        self.failover_threshold_spin.setEnabled(monitoring and self.failover_check.isChecked())

    def _sync_fragment(self) -> None:
        active = self.fragment_check.isChecked()
        for edit in (
            self.fragment_packets_edit,
            self.fragment_length_edit,
            self.fragment_delay_edit,
        ):
            edit.setEnabled(active)

    def _load(self) -> None:
        config = self._config
        self.address_edit.setText(config.inbound_address)
        self.port_spin.setValue(int(config.inbound_socks_port))
        self.mode_combo.select(getattr(config, "proxy_mode", ProxyMode.TUN))
        self.tun_name_edit.setText(getattr(config, "tun_name", DEFAULT_TUN_NAME))
        self.tun_mtu_spin.setValue(int(getattr(config, "tun_mtu", 1500)))
        self.kill_switch_check.setChecked(bool(getattr(config, "tun_kill_switch", False)))
        self._sync_mode()
        self.theme_combo.blockSignals(True)
        self.theme_combo.select(normalize_theme(getattr(config, "theme", None)))
        self.theme_combo.blockSignals(False)
        self.close_to_tray_check.setChecked(config.close_to_tray)
        self.log_level_combo.select(getattr(config, "log_level", DEFAULT_LOG_LEVEL))

        monitoring = config.monitoring
        self.monitoring_check.setChecked(monitoring.enabled)
        self.interval_spin.setValue(int(monitoring.check_interval_seconds))
        self.failover_check.setChecked(monitoring.failover_enabled)
        self.failover_threshold_spin.setValue(int(monitoring.failover_threshold))
        self._sync_monitoring()

        dns = config.dns
        self.dns_combo.select(dns.provider)
        self.dns_url_edit.setText(dns.custom_url)
        self.dns_additional_edit.setText(dns.additional_url)
        self.dns_proxy_check.setChecked(dns.use_proxy)
        self.dns_intercept_check.setChecked(getattr(dns, "intercept", True))

        fragment = config.tls_fragment
        self.fragment_check.setChecked(fragment.enabled)
        self.fragment_packets_edit.setText(fragment.packets)
        self.fragment_length_edit.setText(fragment.length)
        self.fragment_delay_edit.setText(fragment.delay)
        self._sync_fragment()
        self.mux_check.setChecked(config.mux_default_on)

        self._load_routing()

    def save(self) -> bool:
        """Проверить копию настроек и только тогда перенести её в живые."""
        config = copy.deepcopy(self._config)
        config.inbound_address = self.address_edit.text().strip()
        config.inbound_socks_port = self.port_spin.value()
        config.proxy_mode = self.mode_combo.selected()
        config.tun_name = self.tun_name_edit.text().strip()
        config.tun_mtu = self.tun_mtu_spin.value()
        config.tun_kill_switch = self.kill_switch_check.isChecked()
        config.log_level = self.log_level_combo.selected()
        config.theme = self.theme_combo.selected()
        config.close_to_tray = self.close_to_tray_check.isChecked()

        config.monitoring.enabled = self.monitoring_check.isChecked()
        config.monitoring.check_interval_seconds = self.interval_spin.value()
        config.monitoring.failover_enabled = self.failover_check.isChecked()
        config.monitoring.failover_threshold = self.failover_threshold_spin.value()

        config.dns.provider = self.dns_combo.selected()
        config.dns.custom_url = self.dns_url_edit.text().strip()
        config.dns.additional_url = self.dns_additional_edit.text().strip()
        config.dns.use_proxy = self.dns_proxy_check.isChecked()
        config.dns.intercept = self.dns_intercept_check.isChecked()

        config.tls_fragment = TlsFragmentSettings(
            enabled=self.fragment_check.isChecked(),
            packets=self.fragment_packets_edit.text(),
            length=self.fragment_length_edit.text(),
            delay=self.fragment_delay_edit.text(),
        )
        config.mux_default_on = self.mux_check.isChecked()

        self.about.store(config)

        if self.routing.values() != self._routing_loaded:
            from src.ui.logic.routing_import import store_shared_routing

            routing = copy.deepcopy(config.routing)
            try:
                self.routing.read(routing)
            except ValueError as error:
                self.status.setProperty("error", True)
                self.status.setText(invalid_text(str(error)))
                mark_error(self.status, self.status.text())
                self.status.show()
                return False
            store_shared_routing(config, routing)

        errors = validate_settings(config)
        self.validation_errors = errors
        for field, attribute in ERROR_FIELDS.items():
            mark_error(getattr(self, attribute), errors.get(field))
        if errors:
            self.status.setProperty("error", True)
            self.status.setText(invalid_text(next(iter(errors.values()))))
            mark_error(self.status, self.status.text())
            self.status.show()
            return False
        self._config.__dict__.update(config.__dict__)
        from src.ui.logic.routing_form import form_values

        # Записанное — новая точка отсчёта: `refresh` не перечитает форму поверх.
        self._routing_loaded = form_values(self._config.routing)
        self._persisted = None
        self.settings_saved.emit()
        if self._persisted is not True:
            self.status.setText(SAVE_FAILED)
            self.status.setProperty("error", True)
            mark_error(self.status, self.status.text())
            self.status.show()
            return False
        self.status.setProperty("error", False)
        from src.ui.logic.settings_state import pending_settings

        self.status.setText(
            save_status_text(saved=True, reconnect=bool(pending_settings(self._context)))
        )
        mark_error(self.status, None)
        self.status.show()
        return True

    # --- окно ---

    def set_save_result(self, saved: bool) -> None:
        self._persisted = saved

    def refresh(self) -> None:
        """Данные приложения изменились: список подписок и общая маршрутизация."""
        from src.ui.logic.routing_form import form_values

        self.about.refresh_app_update()
        self.subscriptions.refresh()
        self.routing_extra_group.setVisible(self._config.routing_backup is not None)
        self.routing_extra.setRowVisible(
            self.restore_routing_row, self._config.routing_backup is not None
        )
        # Импорт или откат при открытом окне: показать новые правила. Свои
        # несохранённые правки пользователя при этом не трогаются.
        if form_values(self._shared_routing()) != self._routing_loaded:
            self._load_routing()

    def show_section(self, title: str) -> None:
        self.sections.setCurrentRow(SECTIONS.index(title))
