"""Panel that displays discovered MCP tools."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.safety import categorise_tool


class ToolsWidget(QWidget):
    """Shows tool names, categories (read/write), and descriptions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._tools: list[Any] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tools(self, tools: list[Any]) -> None:
        """Populate the list; safe to call from any thread via Qt signals."""
        self._tools = tools
        self._list.clear()
        for tool in tools:
            category = categorise_tool(tool.name)
            icon = "✏️" if category == "write" else "👁"
            item = QListWidgetItem(f"{icon}  {tool.name}")
            item.setData(Qt.UserRole, tool)
            item.setToolTip(tool.description or "")
            self._list.addItem(item)
        self._count_label.setText(f"{len(tools)} tool(s) discovered")

    def clear_tools(self) -> None:
        self._list.clear()
        self._detail.clear()
        self._count_label.setText("Not connected")
        self._tools = []

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        group = QGroupBox("Available Tools")
        inner = QVBoxLayout(group)

        self._count_label = QLabel("Not connected")
        inner.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        inner.addWidget(self._list)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(120)
        self._detail.setPlaceholderText("Select a tool to see its schema…")
        inner.addWidget(self._detail)

        root.addWidget(group)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_item_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self._detail.clear()
            return
        tool = current.data(Qt.UserRole)
        if tool is None:
            return
        import json

        schema = json.dumps(tool.inputSchema or {}, indent=2)
        self._detail.setPlainText(
            f"Name:  {tool.name}\n"
            f"Type:  {categorise_tool(tool.name)}\n"
            f"Desc:  {tool.description or '—'}\n\n"
            f"Schema:\n{schema}"
        )
