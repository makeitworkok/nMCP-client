# Copyright (c) 2026 Chris Favre. All rights reserved.
"""About dialog for app metadata and update-check roadmap."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class AboutDialog(QDialog):
    """Show app metadata, attribution, and update-check placeholder."""

    def __init__(
        self,
        app_name: str,
        version: str,
        author_name: str,
        repo_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {app_name}")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build_ui(app_name, version, author_name, repo_url)

    def _build_ui(
        self,
        app_name: str,
        version: str,
        author_name: str,
        repo_url: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"<b>{app_name}</b>")
        title.setAlignment(Qt.AlignLeft)
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)

        info = QLabel(
            f"Version: {version}\n"
            f"Author: {author_name}\n"
            f"Repository: <a href='{repo_url}'>{repo_url}</a>"
        )
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        updates = QTextBrowser()
        updates.setOpenExternalLinks(False)
        updates.setReadOnly(True)
        updates.setMaximumHeight(140)
        updates.setHtml(
            "<b>Update Checks (Planned)</b><br>"
            "A future release will support checking for newer versions. "
            "This placeholder intentionally does not perform network calls yet."
        )
        layout.addWidget(updates)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)
