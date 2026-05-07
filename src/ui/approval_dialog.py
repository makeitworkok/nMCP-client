"""Approval dialog — shown before executing write tools."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ApprovalDialog(QDialog):
    """Modal dialog asking the user to approve or reject a write tool call."""

    def __init__(
        self,
        tool_name: str,
        args_json: str,
        explanation: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Approve Tool Execution")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui(tool_name, args_json, explanation)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(
        self, tool_name: str, args_json: str, explanation: str
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Warning header
        header = QLabel(f"⚠️  Write operation requested: <b>{tool_name}</b>")
        header.setStyleSheet("font-size: 13px; color: #b45309;")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Plain-English explanation
        desc = QLabel(explanation)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Arguments box
        args_group = QGroupBox("Arguments (JSON)")
        args_inner = QVBoxLayout(args_group)
        args_view = QTextEdit()
        args_view.setReadOnly(True)
        args_view.setPlainText(args_json)
        args_view.setFixedHeight(140)
        args_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        args_inner.addWidget(args_view)
        layout.addWidget(args_group)

        # Approve / Reject buttons
        btn_box = QDialogButtonBox()
        approve_btn = btn_box.addButton("Approve ✓", QDialogButtonBox.AcceptRole)
        reject_btn = btn_box.addButton("Reject ✗", QDialogButtonBox.RejectRole)
        approve_btn.setStyleSheet("background: #16a34a; color: white; font-weight: bold;")
        reject_btn.setStyleSheet("background: #dc2626; color: white; font-weight: bold;")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
