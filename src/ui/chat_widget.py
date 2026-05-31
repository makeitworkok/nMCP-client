# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Chat / workbench widget — message display + user input."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig

_STYLE_USER = (
    "background:#dbeafe; border-left:3px solid #3b82f6; "
    "border-radius:4px; padding:8px 10px; margin:4px 0;"
)
_STYLE_ASSISTANT = (
    "background:#dcfce7; border-left:3px solid #22c55e; "
    "border-radius:4px; padding:8px 10px; margin:4px 0;"
)
_STYLE_TOOL = (
    "background:#fef3c7; border-left:3px solid #f59e0b; "
    "border-radius:4px; padding:6px 10px; margin:2px 0; "
    "font-size:0.88em; font-family:monospace;"
)
_STYLE_SYSTEM = (
    "color:#64748b; font-style:italic; "
    "margin:2px 0; font-size:0.85em; padding:2px 4px;"
)
_STYLE_ERROR = (
    "background:#fee2e2; border-left:3px solid #ef4444; "
    "color:#991b1b; border-radius:4px; padding:6px 10px; margin:2px 0;"
)


class ChatWidget(QWidget):
    """Displays the conversation and accepts user input."""

    message_submitted = Signal(str)
    conversation_selected = Signal(str)
    conversation_create_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pending_assistant = False  # True while streaming assistant chunks
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API — safe to call from Qt main thread (via signals)
    # ------------------------------------------------------------------

    def load_config(self, _config: AppConfig) -> None:
        """Reserved for future config-dependent chat settings."""

    def set_conversations(self, items: list[tuple[str, str]], active_id: str = "") -> None:
        """Populate conversation picker with (conversation_id, title) tuples."""
        self._conversation_combo.blockSignals(True)
        self._conversation_combo.clear()
        for conv_id, title in items:
            self._conversation_combo.addItem(title, conv_id)

        if active_id:
            idx = self._conversation_combo.findData(active_id)
            if idx >= 0:
                self._conversation_combo.setCurrentIndex(idx)
        self._conversation_combo.blockSignals(False)

    def load_history(self, messages: list[tuple[str, str]]) -> None:
        """Render stored conversation messages in chronological order."""
        self.clear()
        for role, text in messages:
            lowered = role.lower()
            if lowered == "user":
                self.append_user_message(text)
            elif lowered == "assistant":
                self.complete_assistant_message(text)
            elif lowered == "tool":
                self._append_block(
                    f'<div style="{_STYLE_TOOL}">🔧 {_esc(text)}</div>'
                )
            elif lowered == "error":
                self.append_error_message(text)
            else:
                self.append_system_message(text)

    @Slot(str)
    def append_user_message(self, text: str) -> None:
        self._append_block(
            f'<div style="{_STYLE_USER}"><b>You:</b> {_esc(text)}</div>'
        )
        self._pending_assistant = False

    @Slot(str)
    def append_assistant_chunk(self, text: str) -> None:
        """Append streaming text to the current assistant block (or start a new one)."""
        if not self._pending_assistant:
            self._display.append(
                f'<div style="{_STYLE_ASSISTANT}" id="assistant-pending">'
                f"<b>Assistant:</b> "
            )
            self._pending_assistant = True
        # Append raw (already inside the div opened above)
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(_esc(text))
        self._display.setTextCursor(cursor)
        self._scroll_to_bottom()

    @Slot(str)
    def complete_assistant_message(self, text: str) -> None:
        """Finalise the assistant turn with the complete message."""
        if self._pending_assistant:
            # Close the open streaming block and start fresh below
            cursor = self._display.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertHtml("</div>")
            self._pending_assistant = False
        else:
            self._append_block(
                f'<div style="{_STYLE_ASSISTANT}"><b>Assistant:</b> {_esc(text)}</div>'
            )
        self._scroll_to_bottom()

    @Slot(str, str)
    def append_tool_result(self, tool_name: str, result_preview: str) -> None:
        self._append_block(
            f'<div style="{_STYLE_TOOL}">'
            f"🔧 <b>{_esc(tool_name)}</b>: {_esc(result_preview)}"
            f"</div>"
        )

    @Slot(str)
    def append_system_message(self, text: str) -> None:
        self._append_block(f'<div style="{_STYLE_SYSTEM}">{_esc(text)}</div>')

    @Slot(str)
    def append_error_message(self, text: str) -> None:
        self._append_block(f'<div style="{_STYLE_ERROR}">⚠ {_esc(text)}</div>')

    def clear(self) -> None:
        self._display.clear()
        self._pending_assistant = False

    def is_plan_mode_enabled(self) -> bool:
        return self._plan_mode_toggle.isChecked()

    def is_strict_paths_enabled(self) -> bool:
        return self._strict_paths_toggle.isChecked()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        thread_row = QHBoxLayout()
        thread_label = QLabel("Conversation:")
        thread_label.setStyleSheet("color:#334155; font-size:11px;")
        thread_row.addWidget(thread_label)

        self._conversation_combo = QComboBox()
        self._conversation_combo.currentIndexChanged.connect(self._on_conversation_changed)
        thread_row.addWidget(self._conversation_combo, stretch=1)

        self._new_conversation_btn = QPushButton("New")
        self._new_conversation_btn.setFixedWidth(60)
        self._new_conversation_btn.clicked.connect(self.conversation_create_requested)
        thread_row.addWidget(self._new_conversation_btn)

        root.addLayout(thread_row)

        mode_row = QHBoxLayout()
        self._plan_mode_toggle = QCheckBox("Plan Mode")
        self._plan_mode_toggle.setToolTip(
            "When enabled, you must approve a generated plan before write actions can run."
        )
        mode_row.addWidget(self._plan_mode_toggle)

        mode_hint = QLabel("Review plan first, then execute")
        mode_hint.setStyleSheet("color:#64748b; font-size:11px;")
        mode_row.addWidget(mode_hint)

        self._strict_paths_toggle = QCheckBox("Strict Paths")
        self._strict_paths_toggle.setChecked(True)
        self._strict_paths_toggle.setToolTip(
            "When enabled, the agent must confirm all component paths before using them. "
            "Disable to allow the agent to infer paths from context."
        )
        mode_row.addWidget(self._strict_paths_toggle)

        mode_row.addStretch()
        root.addLayout(mode_row)

        self._display = QTextBrowser()
        self._display.setOpenExternalLinks(False)
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._display.setStyleSheet(
            "background:#ffffff; border:1px solid #cbd5e1; border-radius:6px; padding:4px;"
        )
        root.addWidget(self._display, stretch=1)

        # ── Input row ────────────────────────────────────────────────
        input_row = QHBoxLayout()

        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Type a message… (Enter to send, Shift+Enter for newline)"
        )
        self._input.setFixedHeight(72)
        self._input.installEventFilter(self)

        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedWidth(70)
        self._send_btn.setFixedHeight(72)
        self._send_btn.clicked.connect(self._on_send)

        input_row.addWidget(self._input)
        input_row.addWidget(self._send_btn)
        root.addLayout(input_row)

    # ------------------------------------------------------------------
    # Event filter — intercept Enter key in input box
    # ------------------------------------------------------------------

    def eventFilter(self, obj: object, event: object) -> bool:
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        if obj is self._input and isinstance(event, QKeyEvent):
            if (
                event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Return
                and not (event.modifiers() & Qt.ShiftModifier)
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self._input.setEnabled(False)
        self._send_btn.setEnabled(False)
        self.message_submitted.emit(text)

    def _on_conversation_changed(self, index: int) -> None:
        if index < 0:
            return
        conv_id = str(self._conversation_combo.itemData(index) or "")
        if conv_id:
            self.conversation_selected.emit(conv_id)

    def enable_input(self) -> None:
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._input.setFocus()

    def disable_input(self) -> None:
        self._input.setEnabled(False)
        self._send_btn.setEnabled(False)

    def _append_block(self, html_block: str) -> None:
        self._display.append(html_block)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        bar = self._display.verticalScrollBar()
        bar.setValue(bar.maximum())


def _esc(text: str) -> str:
    """HTML-escape user/LLM text for safe insertion into QTextBrowser."""
    return html.escape(text).replace("\n", "<br>")
