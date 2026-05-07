"""Chat / workbench widget — message display + user input."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig

_STYLE_USER = "background:#dbeafe; border-radius:6px; padding:6px; margin:4px 0;"
_STYLE_ASSISTANT = "background:#f0fdf4; border-radius:6px; padding:6px; margin:4px 0;"
_STYLE_TOOL = "background:#fefce8; border-radius:6px; padding:4px; margin:2px 0; font-size:0.9em;"
_STYLE_SYSTEM = "color:#6b7280; font-style:italic; margin:2px 0; font-size:0.9em;"
_STYLE_ERROR = "color:#dc2626; font-style:italic; margin:2px 0;"


class ChatWidget(QWidget):
    """Displays the conversation and accepts user input."""

    message_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pending_assistant = False  # True while streaming assistant chunks
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API — safe to call from Qt main thread (via signals)
    # ------------------------------------------------------------------

    def load_config(self, _config: AppConfig) -> None:
        """Reserved for future config-dependent chat settings."""

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

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._display = QTextBrowser()
        self._display.setOpenExternalLinks(False)
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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

    def enable_input(self) -> None:
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._input.setFocus()

    def _append_block(self, html_block: str) -> None:
        self._display.append(html_block)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        bar = self._display.verticalScrollBar()
        bar.setValue(bar.maximum())


def _esc(text: str) -> str:
    """HTML-escape user/LLM text for safe insertion into QTextBrowser."""
    return html.escape(text).replace("\n", "<br>")
