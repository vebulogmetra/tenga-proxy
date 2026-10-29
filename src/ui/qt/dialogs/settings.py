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
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
from src.sub.device import ensure_hwid
from src.sys import tun_access
from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.settings_form import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_TUN_NAME,
    LOG_LEVELS,
    validate_settings,
)
from src.ui.qt.dialogs.base import FORM_STYLE, Debounce, KeyedCombo, mark_error, watch
from src.ui.qt.theme import apply_theme

if TYPE_CHECKING:
    from src.ui.qt.dialogs.settings_pages import AboutPage, SubscriptionsPage

SECTIONS = ("Общие", "Мониторинг", "DNS", "Обход блокировок", "Подписки", "О программе")

# Поле проверки (`validate_settings`) → атрибут виджета.
ERROR_FIELDS = {
    "address": "address_edit",
    "tun_name": "tun_name_edit",
    "dns_url": "dns_url_edit",
    "dns_additional": "dns_additional_edit",
    "fragment_packets": "fragment_packets_edit",
    "fragment_length": "fragment_length_edit",
    "fragment_delay": "fragment_delay_edit",
    "sub_exceptions": "sub_exceptions_edit",
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
    for group in groups:
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
        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(640, 440)
        self.setStyleSheet(FORM_STYLE)
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
        self.sections.addItems(list(SECTIONS))
        self.sections.setFixedWidth(180)
        self.pages = QStackedWidget()
        for widget in (
            self._general_page(),
            self._monitoring_page(),
            self._dns_page(),
            self._bypass_page(),
            page(self.subscriptions, self._request_group()),
            page(self.about),
        ):
            self.pages.addWidget(widget)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(0)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("error", True)
        self.status.hide()
        buttons = QDialogButtonBox()
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._load()
        self.autosave = Debounce(self.save, parent=self)
        watch(self._fields(), self.autosave.queue)
        self.finished.connect(lambda _result: self.autosave.flush())

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
        form.addRow(self.close_to_tray_check)

        logs = QGroupBox("Журнал")
        form = QFormLayout(logs)
        self.log_level_combo = KeyedCombo(LOG_LEVELS, {level: level for level in LOG_LEVELS})
        form.addRow("Уровень подробности", self.log_level_combo)
        return page(inbound, runtime, window, logs)

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
        form.addRow(
            hint("Если сервер перестал отвечать, подключается другой профиль той же группы")
        )
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

    def _bypass_page(self) -> QWidget:
        fragment = QGroupBox("Фрагментация TLS")
        form = QFormLayout(fragment)
        form.addRow(
            hint(
                "Делит начало TLS-соединения на части, чтобы фильтр не разобрал имя "
                "сервера. Действует на профили с TLS и Reality. Вступает в силу после "
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

    def _request_group(self) -> QWidget:
        request = QGroupBox("Запрос к провайдеру")
        form = QFormLayout(request)
        form.addRow(
            hint(
                f"Пустое поле — {DEFAULT_USER_AGENT}: так представляется большинство "
                "клиентов, и провайдеры отдают ему обычный список серверов."
            )
        )
        self.user_agent_edit = QLineEdit()
        self.user_agent_edit.setPlaceholderText(DEFAULT_USER_AGENT)
        form.addRow("User-Agent", self.user_agent_edit)
        self.device_info_check = check(
            "Отправлять данные устройства",
            "Идентификатор, система и модель. Нужны провайдерам, которые считают лимит устройств",
        )
        form.addRow(self.device_info_check)
        self.sub_exceptions_edit = QLineEdit()
        self.sub_exceptions_edit.setToolTip("Через пробел")
        form.addRow("Разрешённые HTTP/LAN URL", self.sub_exceptions_edit)
        self.sub_insecure_check = check(
            "Не проверять TLS-сертификат подписок",
            "Отдельное исключение; не разрешает доступ к HTTP или локальной сети",
        )
        form.addRow(self.sub_insecure_check)
        return request

    def _fields(self) -> list[QWidget]:
        return [
            self.address_edit,
            self.port_spin,
            self.mode_combo,
            self.tun_name_edit,
            self.tun_mtu_spin,
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
            self.user_agent_edit,
            self.device_info_check,
            self.sub_exceptions_edit,
            self.sub_insecure_check,
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
        self.tun_name_edit.setEnabled(tun)
        self.tun_mtu_spin.setEnabled(tun)
        if tun and self._tun_problems is None:
            self._check_tun_access()
        self._sync_tun_access()

    def _check_tun_access(self) -> None:
        # sudo и служба отвечают не мгновенно: открытие окна ждать не должно.
        from src.core.config import find_xray_binary

        self._tun_problems = []
        self.tun_access_thread = self.run(
            lambda: tun_access.tun_problems(find_xray_binary()),
            self._on_tun_access_checked,
            name="tenga-tun-access",
        )

    def _on_tun_access_checked(self, problems: list[str]) -> None:
        self._tun_problems = list(problems)
        self._sync_tun_access()

    def _sync_tun_access(self) -> None:
        problems = self._tun_problems or []
        self.tun_access_label.setText("TUN не заработает:\n" + "\n".join(problems))
        self.tun_access_label.setVisible(
            self.mode_combo.selected() == ProxyMode.TUN and bool(problems)
        )

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

        user_agent = config.user_agent.strip()
        self.user_agent_edit.setText("" if user_agent == LEGACY_USER_AGENT else user_agent)
        self.device_info_check.setChecked(config.sub_send_device_info)
        self.sub_exceptions_edit.setText(" ".join(config.sub_source_exceptions))
        self.sub_insecure_check.setChecked(config.sub_insecure)

    def save(self) -> bool:
        """Проверить копию настроек и только тогда перенести её в живые."""
        config = copy.deepcopy(self._config)
        config.inbound_address = self.address_edit.text().strip()
        config.inbound_socks_port = self.port_spin.value()
        config.proxy_mode = self.mode_combo.selected()
        config.tun_name = self.tun_name_edit.text().strip()
        config.tun_mtu = self.tun_mtu_spin.value()
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

        config.user_agent = self.user_agent_edit.text().strip()
        config.sub_source_exceptions = self.sub_exceptions_edit.text().split()
        config.sub_insecure = self.sub_insecure_check.isChecked()
        config.sub_send_device_info = self.device_info_check.isChecked()
        if config.sub_send_device_info:
            # Идентификатор сохранится вместе с остальными настройками.
            ensure_hwid(config)
        self.about.store(config)

        errors = validate_settings(config)
        self.validation_errors = errors
        for field, attribute in ERROR_FIELDS.items():
            mark_error(getattr(self, attribute), errors.get(field))
        if errors:
            self.status.setText("Исправьте настройки: " + next(iter(errors.values())))
            self.status.show()
            return False
        self.status.hide()
        self._config.__dict__.update(config.__dict__)
        self.settings_saved.emit()
        return True

    # --- окно ---

    def refresh(self) -> None:
        """Данные приложения изменились: список подписок и откат маршрутизации."""
        self.subscriptions.refresh()
        self.about.refresh()

    def show_section(self, title: str) -> None:
        self.sections.setCurrentRow(SECTIONS.index(title))
