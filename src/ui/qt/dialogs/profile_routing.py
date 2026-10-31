"""VPN и маршрутизация одного профиля.

Как в GTK: кнопки «Сохранить» нет, правки сохраняются через полсекунды
после последней и при закрытии окна.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.ui.logic import platform_texts
from src.ui.logic.forms import parse_host_list
from src.ui.logic.routing_form import (
    BLOCK_HINT,
    LIST_HINT,
    ORDER_LABELS,
    ORDER_PRESETS,
    current_catalog,
    order_key,
    ru_direct_subtitle,
)
from src.ui.qt.dialogs.base import Debounce, FormStyle, KeyedCombo, mark_error, watch

LISTS = (
    ("block", "Блокировать", BLOCK_HINT),
    ("proxy", "Через прокси", LIST_HINT),
    ("direct", "Напрямую", LIST_HINT),
    ("vpn", "Через VPN", LIST_HINT),
)


def _check(text: str, subtitle: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(subtitle)
    return box


class ProfileRoutingDialog(QDialog):
    routing_saved = Signal()

    def __init__(self, profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VPN и маршруты")
        self.setModal(True)
        self.setMinimumSize(560, 600)
        self._form_style = FormStyle(self)
        self._profile = profile
        self.lists: dict[str, QPlainTextEdit] = {}

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_vpn_page(), "VPN")
        self.tabs.addTab(self._scrolled(self._build_routing_page()), "Маршрутизация")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("error", True)
        self.status.hide()
        buttons = QDialogButtonBox()
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._load()
        self.autosave = Debounce(self.save, parent=self)
        watch(
            [
                self.name_edit,
                self.vpn_check,
                self.vpn_name_edit,
                self.vpn_auto_check,
                self.vpn_interface_edit,
                self.direct_interface_edit,
                self.mode_combo,
                self.order_combo,
                self.bypass_check,
                self.ru_direct_check,
                *self.lists.values(),
            ],
            self.autosave.queue,
        )
        self.finished.connect(lambda _result: self.autosave.flush())

    # --- страницы ---

    @staticmethod
    def _scrolled(body: QWidget) -> QScrollArea:
        # Четыре списка не помещаются в окно целиком: прокрутка вместо сжатия.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    def _build_vpn_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)

        profile = QGroupBox("Профиль")
        form = QFormLayout(profile)
        self.name_edit = QLineEdit()
        form.addRow("Имя", self.name_edit)
        self.address_label = QLabel()
        self.address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Сервер", self.address_label)
        column.addWidget(profile)

        vpn = QGroupBox(platform_texts.vpn_group_title())
        form = QFormLayout(vpn)
        description = QLabel(platform_texts.vpn_group_description())
        description.setWordWrap(True)
        form.addRow(description)
        self.vpn_check = QCheckBox("Использовать VPN")
        self.vpn_check.toggled.connect(self._sync_vpn)
        form.addRow(self.vpn_check)
        self.vpn_name_edit = QLineEdit()
        form.addRow("Имя подключения", self.vpn_name_edit)
        self.vpn_auto_check = _check(
            "Подключать автоматически",
            "Поднимать VPN при запуске профиля и опускать при остановке",
        )
        form.addRow(self.vpn_auto_check)
        column.addWidget(vpn)

        interfaces = QGroupBox("Интерфейсы")
        form = QFormLayout(interfaces)
        self.vpn_interface_edit = QLineEdit()
        self.vpn_interface_edit.setPlaceholderText("Определять автоматически")
        form.addRow("Интерфейс VPN", self.vpn_interface_edit)
        self.direct_interface_edit = QLineEdit()
        self.direct_interface_edit.setPlaceholderText("Определять автоматически")
        form.addRow("Интерфейс прямого выхода", self.direct_interface_edit)
        column.addWidget(interfaces)
        column.addStretch(1)
        return page

    def _build_routing_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)

        mode = QGroupBox("Режим")
        form = QFormLayout(mode)
        self.mode_combo = KeyedCombo(RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Правила", self.mode_combo)
        self.order_combo = KeyedCombo(ORDER_PRESETS, ORDER_LABELS)
        form.addRow("Приоритет групп", self.order_combo)
        self.bypass_check = _check(
            "Локальные сети напрямую",
            "127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
        )
        form.addRow(self.bypass_check)
        self.ru_direct_check = _check(
            "Российские сайты и IP напрямую", ru_direct_subtitle(current_catalog())
        )
        form.addRow(self.ru_direct_check)
        column.addWidget(mode)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for key, title, hint in LISTS:
            box = QGroupBox(title)
            box.setToolTip(hint)
            inner = QVBoxLayout(box)
            edit = QPlainTextEdit()
            edit.setFont(font)
            edit.setPlaceholderText(hint)
            edit.setMinimumHeight(110)
            inner.addWidget(edit)
            self.lists[key] = edit
            column.addWidget(box)
        return page

    # --- состояние ---

    def _sync_vpn(self) -> None:
        enabled = self.vpn_check.isChecked()
        for widget in (
            self.vpn_name_edit,
            self.vpn_auto_check,
            self.vpn_interface_edit,
            self.direct_interface_edit,
        ):
            widget.setEnabled(enabled)

    def _sync_mode(self) -> None:
        # В режиме «всё через прокси» списки не применяются: активными они
        # обещали бы несуществующий эффект. «Локальные сети» действуют всегда.
        custom = self.mode_combo.selected() == RoutingMode.CUSTOM
        for widget in (*self.lists.values(), self.order_combo, self.ru_direct_check):
            widget.setEnabled(custom)

    def _load(self) -> None:
        profile = self._profile
        bean = profile.bean
        self.name_edit.setText(bean.display_name)
        self.address_label.setText(f"{bean.server_address}:{bean.server_port}")

        vpn = getattr(profile, "vpn_settings", None) or VpnSettings()
        self.vpn_check.setChecked(vpn.enabled)
        self.vpn_name_edit.setText(vpn.connection_name)
        self.vpn_auto_check.setChecked(getattr(vpn, "auto_connect", False))
        self.vpn_interface_edit.setText(getattr(vpn, "interface_name", "") or "")
        self.direct_interface_edit.setText(getattr(vpn, "direct_interface", "") or "")
        self._sync_vpn()

        routing = getattr(profile, "routing_settings", None) or RoutingSettings()
        self.mode_combo.select(routing.mode)
        self.bypass_check.setChecked(routing.bypass_local_networks)
        self.ru_direct_check.setChecked(getattr(routing, "ru_direct", False))
        try:
            order = routing.get_rule_order()
        except AttributeError:
            order = []
        self.order_combo.select(order_key(order))
        for key, edit in self.lists.items():
            edit.setPlainText("\n".join(getattr(routing, f"{key}_list", None) or []))
        self._sync_mode()

    def save(self) -> bool:
        """Записать форму в профиль; ошибка в списке — ничего не меняется."""
        lists: dict[str, list[str]] = {}
        first_error = ""
        for key, edit in self.lists.items():
            try:
                lists[key] = parse_host_list(edit.toPlainText())
                mark_error(edit, None)
            except ValueError as error:
                mark_error(edit, str(error))
                first_error = first_error or str(error)
        self.status.setText(first_error)
        self.status.setVisible(bool(first_error))
        if first_error:
            return False

        profile = self._profile
        name = self.name_edit.text().strip()
        if name:
            profile.bean.name = name

        if getattr(profile, "vpn_settings", None) is None:
            profile.vpn_settings = VpnSettings()
        vpn = profile.vpn_settings
        vpn.enabled = self.vpn_check.isChecked()
        # Безымянное подключение система не найдёт — остаётся прежнее.
        connection_name = self.vpn_name_edit.text().strip()
        if connection_name:
            vpn.connection_name = connection_name
        vpn.auto_connect = self.vpn_auto_check.isChecked()
        vpn.interface_name = self.vpn_interface_edit.text().strip()
        vpn.direct_interface = self.direct_interface_edit.text().strip()

        if getattr(profile, "routing_settings", None) is None:
            profile.routing_settings = RoutingSettings()
        routing = profile.routing_settings
        routing.mode = self.mode_combo.selected()
        routing.bypass_local_networks = self.bypass_check.isChecked()
        routing.ru_direct = self.ru_direct_check.isChecked()
        routing.rule_order = list(ORDER_PRESETS[self.order_combo.selected()])
        for key, values in lists.items():
            setattr(routing, f"{key}_list", values)

        self.routing_saved.emit()
        return True
