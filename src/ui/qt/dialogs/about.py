"""О программе: версии приложения и ядра, ссылка на проект."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.core.config import get_asset_path
from src.ui.qt.dialogs.base import copy_text

WEBSITE = "https://github.com/vebulogmetra/tenga-proxy"
DEVELOPER = "Artem G."
LOGO_SIZE = 96


def debug_info(version: str, core: str) -> str:
    """Строка для отчёта об ошибке: обе версии рядом, как в GTK."""
    return f"Veblock {version}\nxray-core {core}"


class AboutDialog(QDialog):
    def __init__(self, version: str, core: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setModal(True)
        self._debug_info = debug_info(version, core)

        logo = QLabel()
        pixmap = QPixmap(str(get_asset_path("tenga-proxy.png")))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(
                    LOGO_SIZE,
                    LOGO_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        name = QLabel("Veblock")
        name.setObjectName("aboutName")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        name.setFont(font)
        self.version_label = QLabel(f"Версия {version}")
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        comment = QLabel(f"Клиент прокси на базе xray-core {core}")
        comment.setWordWrap(True)
        link = QLabel(f'<a href="{WEBSITE}">{WEBSITE}</a>')
        link.setOpenExternalLinks(True)
        credits = QLabel(f"Разработчик: {DEVELOPER} · Лицензия MIT")

        texts = QVBoxLayout()
        for widget in (name, self.version_label, comment, link, credits):
            texts.addWidget(widget)
        head = QHBoxLayout()
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(texts, 1)

        buttons = QDialogButtonBox()
        self.copy_button = buttons.addButton(
            "Копировать сведения", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.copy_button.clicked.connect(lambda: copy_text(self._debug_info))
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(buttons)
