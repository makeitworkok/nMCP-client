# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Widget for displaying local memory/SQLite health information."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget


class MemoryHealthWidget(QWidget):
    """Displays memory SQLite status and key counters for operator visibility."""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.set_snapshot(None)

    def set_snapshot(self, snapshot: Any) -> None:
        """Update labels using a MemoryHealthSnapshot-like object."""
        if snapshot is None:
            self._db_path_value.setText("Not initialized")
            self._db_exists_value.setText("No")
            self._db_size_value.setText("0 B")
            self._station_rows_value.setText("0")
            self._episode_rows_value.setText("0")
            self._lesson_rows_value.setText("0")
            self._last_update_value.setText("-")
            self._last_station_key_value.setText("-")
            return

        self._db_path_value.setText(str(getattr(snapshot, "db_path", "-")))
        self._db_exists_value.setText("Yes" if bool(getattr(snapshot, "exists", False)) else "No")
        self._db_size_value.setText(self._format_bytes(int(getattr(snapshot, "size_bytes", 0))))
        self._station_rows_value.setText(str(getattr(snapshot, "station_profile_rows", 0)))
        self._episode_rows_value.setText(str(getattr(snapshot, "episode_rows", 0)))
        self._lesson_rows_value.setText(str(getattr(snapshot, "tool_lesson_rows", 0)))

        updated = str(getattr(snapshot, "latest_station_updated_at", "") or "-")
        key = str(getattr(snapshot, "latest_station_key", "") or "-")
        self._last_update_value.setText(updated)
        self._last_station_key_value.setText(key)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        group = QGroupBox("Memory Health")
        inner = QVBoxLayout(group)

        form = QFormLayout()
        form.setSpacing(4)

        self._db_path_value = QLabel()
        self._db_path_value.setWordWrap(True)
        self._db_path_value.setStyleSheet("font-size:11px; color:#334155;")
        form.addRow("DB Path:", self._db_path_value)

        self._db_exists_value = QLabel()
        form.addRow("DB Exists:", self._db_exists_value)

        self._db_size_value = QLabel()
        form.addRow("DB Size:", self._db_size_value)

        self._station_rows_value = QLabel()
        form.addRow("Stations:", self._station_rows_value)

        self._episode_rows_value = QLabel()
        form.addRow("Episodes:", self._episode_rows_value)

        self._lesson_rows_value = QLabel()
        form.addRow("Tool Lessons:", self._lesson_rows_value)

        self._last_update_value = QLabel()
        self._last_update_value.setWordWrap(True)
        self._last_update_value.setStyleSheet("font-size:11px; color:#334155;")
        form.addRow("Last Update:", self._last_update_value)

        self._last_station_key_value = QLabel()
        self._last_station_key_value.setWordWrap(True)
        self._last_station_key_value.setStyleSheet("font-size:11px; color:#334155;")
        form.addRow("Last Station Key:", self._last_station_key_value)

        inner.addLayout(form)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_requested)
        inner.addWidget(refresh_btn)

        root.addWidget(group)

    def _format_bytes(self, size_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        value = float(size_bytes)
        idx = 0
        while value >= 1024 and idx < len(units) - 1:
            value /= 1024
            idx += 1
        if idx == 0:
            return f"{int(value)} {units[idx]}"
        return f"{value:.1f} {units[idx]}"
