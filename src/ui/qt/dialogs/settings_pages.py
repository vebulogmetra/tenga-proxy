"""Страницы окна настроек со своим поведением: список подписок и «О программе»."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.core_update import evaluate, fetch_releases, known_releases, refresh_known_releases
from src.core.geo import USER_GEO_DIR
from src.core.geo_update import update_geo_bases
from src.ui.controller import CONFIRM_DELETE
from src.ui.logic import platform_texts
from src.ui.logic.routing_form import current_catalog, geo_summary
from src.ui.logic.subscriptions_view import (
    EMPTY_RESPONSE_HINT,
    EMPTY_RESPONSE_TEXT,
    SubscriptionRow,
    build_subscription_rows,
)
from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
from src.ui.qt.dialogs.base import open_url
from src.ui.qt.dialogs.confirm import build_confirmation

if TYPE_CHECKING:
    from src.ui.qt.dialogs.settings import SettingsDialog

ERROR_COLOR = QColor("#d13438")
COLUMNS = ("Название", "Профилей", "Обновлено", "Трафик и срок")
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1


class SubscriptionsPage(QGroupBox):
    """Подписки списком с действиями; в GTK это была отдельная вкладка окна."""

    def __init__(self, dialog: SettingsDialog) -> None:
        super().__init__("Подписки")
        self._dialog = dialog
        self._app = dialog._app
        self._rows: dict[int, SubscriptionRow] = {}

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(160)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit())
        self.tree.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self.empty_label = QLabel("Подписок нет. Добавьте ссылку от провайдера.")
        self.empty_label.setEnabled(False)

        self.add_button = QPushButton("Добавить…")
        self.add_button.clicked.connect(
            lambda: self._app.open_add_subscription(parent=self._dialog)
        )
        self.update_button = QPushButton("Обновить")
        self.update_button.clicked.connect(self._update)
        self.edit_button = QPushButton("Изменить…")
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.clicked.connect(self._delete)
        self.more_button = QPushButton("Ещё")
        self.more_menu = QMenu(self.more_button)
        self.more_button.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(lambda: self._fill_menu(self.more_menu, more=True))

        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.update_button,
            self.edit_button,
            self.delete_button,
            self.more_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addWidget(self.empty_label)
        layout.addLayout(buttons)
        self.refresh()

    # --- данные ---

    def refresh(self) -> None:
        store = self._app.context.profiles
        selected = self.selected_group_id()
        counts = {gid: len(store.get_profiles_in_group(gid)) for gid in store.groups}
        rows = build_subscription_rows(store.groups, counts)
        self._rows = {row.group_id: row for row in rows}
        self.tree.clear()
        for row in rows:
            details = row.details_text
            if row.empty:
                details = " · ".join(part for part in (details, EMPTY_RESPONSE_TEXT) if part)
            item = QTreeWidgetItem([row.name, str(row.profile_count), row.updated_text, details])
            item.setData(0, GROUP_ROLE, row.group_id)
            item.setToolTip(0, row.url)
            if row.announce:
                item.setToolTip(1, row.announce)
            if row.empty:
                item.setToolTip(3, EMPTY_RESPONSE_HINT)
            if row.expired or row.empty:
                # Истёкшую или пустую подписку видно сразу.
                item.setForeground(3, QBrush(ERROR_COLOR))
            self.tree.addTopLevelItem(item)
            if row.group_id == selected:
                self.tree.setCurrentItem(item)
        for column in range(1, len(COLUMNS)):
            self.tree.resizeColumnToContents(column)
        self.tree.setVisible(bool(rows))
        self.empty_label.setVisible(not rows)
        self._sync_buttons()

    def selected_group_id(self) -> int | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, GROUP_ROLE)

    def _selected_row(self) -> SubscriptionRow | None:
        group_id = self.selected_group_id()
        return None if group_id is None else self._rows.get(group_id)

    def _sync_buttons(self) -> None:
        row = self._selected_row()
        for button in (self.update_button, self.edit_button, self.delete_button):
            button.setEnabled(row is not None)
        self.more_button.setEnabled(
            row is not None and bool(row.web_page_url or row.support_url or row.announce)
        )

    # --- действия ---

    def _update(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.controller.update_subscription(group_id)

    def _edit(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.edit_group(group_id, parent=self._dialog)

    def _delete(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.delete_group(group_id, parent=self._dialog)

    def _show_announce(self) -> None:
        row = self._selected_row()
        if row is None or not row.announce:
            return
        box = QMessageBox(
            QMessageBox.Icon.Information,
            "Объявление провайдера",
            row.announce,
            parent=self._dialog,
        )
        # Текст пишет провайдер: только текст, без разметки.
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.open()

    def _fill_menu(self, menu: QMenu, *, more: bool = False) -> None:
        menu.clear()
        row = self._selected_row()
        if row is None:
            return
        if not more:
            menu.addAction("Обновить", self._update)
            menu.addAction("Изменить…", self._edit)
        group_id = row.group_id
        # Ссылки провайдера есть не у каждой подписки: пустой пункт не показываем.
        if row.web_page_url:
            menu.addAction(
                "Страница подписки",
                lambda: self._app.open_subscription_link(group_id, "sub_web_page_url"),
            )
        if row.support_url:
            menu.addAction(
                "Поддержка",
                lambda: self._app.open_subscription_link(group_id, "sub_support_url"),
            )
        if row.announce:
            menu.addAction("Объявление провайдера", self._show_announce)
        if not more:
            menu.addSeparator()
            menu.addAction("Удалить", self._delete)

    def menu_labels(self) -> list[str]:
        menu = QMenu()
        self._fill_menu(menu)
        return [action.text() for action in menu.actions() if not action.isSeparator()]

    def _on_context_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        self._fill_menu(menu)
        menu.exec(self.tree.viewport().mapToGlobal(point))


class AboutPage(QWidget):
    """Версии, проверка обновлений и обслуживание: журналы, геобазы, откат."""

    def __init__(self, dialog: SettingsDialog) -> None:
        super().__init__()
        self._dialog = dialog
        self._app = dialog._app
        self._config = dialog._config
        self._context = dialog._context
        self.fetch_releases = fetch_releases
        self.fetch_app_releases = None
        self.core_update_thread = None
        self.app_update_thread = None

        about = QGroupBox("Veblock")
        form = QFormLayout(about)
        form.addRow("Версия", self._value(app_version()))

        self.app_update_label = QLabel(
            self._config.app_update_target or "Нет сведений о новой версии"
        )
        self.app_check_button = QPushButton("Проверить")
        self.app_check_button.clicked.connect(self.check_app_update)
        self.app_release_button = QPushButton("Открыть релиз")
        self.app_release_button.setEnabled(bool(self._config.app_update_url))
        self.app_release_button.clicked.connect(self._open_app_release)
        form.addRow(
            "Обновление приложения",
            self._with(self.app_update_label, self.app_check_button, self.app_release_button),
        )
        self.app_updates_check = QCheckBox("Проверять обновления приложения раз в сутки")
        self.app_updates_check.setChecked(self._config.app_update_enabled)
        form.addRow(self.app_updates_check)
        self.app_prereleases_check = QCheckBox("Предлагать предварительные версии приложения")
        self.app_prereleases_check.setChecked(self._config.app_update_prerelease)
        form.addRow(self.app_prereleases_check)
        self.core_updates_check = QCheckBox("Проверять обновления ядра раз в три дня")
        self.core_updates_check.setChecked(self._config.core_update_enabled)
        form.addRow(self.core_updates_check)

        self._core_version = core_version(getattr(self._context, "xray_manager", None))
        form.addRow("Ядро xray", self._value(self._core_version))
        self.core_update_label = QLabel()
        self.core_update_button = QPushButton("Проверить")
        self.core_update_button.clicked.connect(self.check_core_update)
        form.addRow("Обновление ядра", self._with(self.core_update_label, self.core_update_button))
        self._show_core_update()
        form.addRow("Конфигурация", self._value(str(self._context.config_dir)))

        maintenance = QGroupBox("Обслуживание")
        form = self._maintenance = QFormLayout(maintenance)
        # Без подтверждения, как в Android: откат возвращает только то, что
        # пользователь сам только что заменил импортом.
        self.restore_routing_button = QPushButton("Вернуть")
        self.restore_routing_button.clicked.connect(
            lambda: self._app.activate_action("restore-routing")
        )
        self.restore_routing_row = self._with(
            QLabel("Режим и списки до последнего импорта ссылкой"), self.restore_routing_button
        )
        form.addRow("Маршрутизация до импорта", self.restore_routing_row)
        self.clear_logs_label = QLabel("Удаляет накопленные файлы логов")
        clear = QPushButton("Очистить")
        clear.clicked.connect(self._on_clear_logs)
        form.addRow("Журналы", self._with(self.clear_logs_label, clear))
        self.geo_label = QLabel(geo_summary(current_catalog()))
        self.geo_label.setTextFormat(Qt.TextFormat.PlainText)
        self.geo_update_button = QPushButton("Обновить")
        self.geo_update_button.clicked.connect(self._on_update_geo)
        form.addRow("Геобазы", self._with(self.geo_label, self.geo_update_button))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(about)
        layout.addWidget(maintenance)
        self.refresh()

    @staticmethod
    def _value(text: str) -> QLabel:
        label = QLabel(text)
        # Настоящее значение копируют в отчёт об ошибке; прочерк — незачем.
        if text != UNKNOWN:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _with(label: QLabel, *buttons: QPushButton) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        for button in buttons:
            row.addWidget(button)
        return box

    def fields(self) -> list[QWidget]:
        return [self.app_updates_check, self.app_prereleases_check, self.core_updates_check]

    def store(self, config) -> None:
        config.app_update_enabled = self.app_updates_check.isChecked()
        config.app_update_prerelease = self.app_prereleases_check.isChecked()
        config.core_update_enabled = self.core_updates_check.isChecked()

    def refresh(self) -> None:
        # Строка видна, только когда есть что возвращать, как в GTK.
        self._maintenance.setRowVisible(
            self.restore_routing_row, self._config.routing_backup is not None
        )

    # --- обновление приложения ---

    def _open_app_release(self) -> None:
        from src.core.app_update import safe_release_url

        url = self._config.app_update_url
        if safe_release_url(url):
            open_url(url)

    def check_app_update(self) -> None:
        from src.core.app_update import check_app_update, fetch_app_releases
        from src.sub.route import local_proxy_url

        self.app_check_button.setEnabled(False)
        self.app_update_label.setText("Проверка…")
        context = self._context
        fetch = self.fetch_app_releases or (
            lambda: fetch_app_releases(lambda: local_proxy_url(context.config, context.proxy_state))
        )

        def done(release) -> None:
            self.app_check_button.setEnabled(True)
            text = f"Доступна версия {release.version}" if release else "Новых версий нет"
            if release and not release.has_asset:
                text += "; " + platform_texts.missing_release_asset()
            self.app_update_label.setText(text)
            self.app_release_button.setEnabled(bool(release))
            context.save_config()

        def failed(_error) -> None:
            self.app_check_button.setEnabled(True)
            self.app_update_label.setText("Не удалось проверить обновления")
            context.save_config()

        self.app_update_thread = self._dialog.run(
            lambda: check_app_update(self._config, app_version(), force=True, fetch=fetch),
            done,
            failed,
            name="tenga-app-update-manual",
        )

    # --- обновление ядра ---

    def _show_core_update(self) -> None:
        status = evaluate(self._core_version, known_releases(self._config))
        self.core_update_label.setText(core_update_text(status))

    def check_core_update(self) -> None:
        self.core_update_button.setEnabled(False)
        self.core_update_label.setText("Проверяю…")

        def done(_releases) -> None:
            self.core_update_button.setEnabled(True)
            self._show_core_update()
            # Время проверки — в настройках: иначе следующий запуск спросил бы снова.
            self._context.save_config()

        def failed(_error) -> None:
            self.core_update_button.setEnabled(True)
            self.core_update_label.setText("Не удалось проверить обновления")

        self.core_update_thread = self._dialog.run(
            lambda: refresh_known_releases(
                self._config, now=time.time(), fetch=self.fetch_releases
            ),
            done,
            failed,
            name="tenga-core-update",
        )

    # --- обслуживание ---

    def _on_clear_logs(self) -> None:
        def clear() -> None:
            self._dialog.run(
                self._context.log_manager.clear_all_logs,
                lambda result: self.clear_logs_label.setText(f"Очищено файлов: {result[0]}"),
                name="tenga-clear-logs",
            )

        build_confirmation(
            CONFIRM_DELETE,
            "Очистить журналы?",
            "Все сохранённые записи будут удалены.",
            clear,
            confirm_label="Очистить",
            parent=self._dialog,
        ).open()

    def _on_update_geo(self) -> None:
        # Десятки мегабайт: в главном потоке окно бы замерло.
        self.geo_update_button.setEnabled(False)
        self.geo_label.setText("Скачивание…")

        def done(catalog) -> None:
            self.geo_update_button.setEnabled(True)
            self.geo_label.setText(f"{geo_summary(catalog)} — применятся после переподключения")
            self._context.proxy_state.notify_listeners()

        def failed(error) -> None:
            self.geo_update_button.setEnabled(True)
            self.geo_label.setText(f"Не обновлены: {error}")

        self._dialog.run(
            lambda: update_geo_bases(USER_GEO_DIR), done, failed, name="tenga-geo-update"
        )
