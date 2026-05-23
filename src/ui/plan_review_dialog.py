# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Plan review dialog shown before Plan Mode execution."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class PlanReviewDialog(QDialog):
    """Allow the user to approve execution, request revision, or cancel."""

    APPROVE_ROLE = 1
    REVISE_ROLE = 2
    CANCEL_ROLE = 3

    def __init__(self, plan_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._decision = self.CANCEL_ROLE
        self.setWindowTitle("Review Execution Plan")
        self.setModal(True)
        self.setMinimumWidth(640)
        self._build_ui(plan_text)

    @property
    def decision(self) -> int:
        return self._decision

    def _build_ui(self, plan_text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel(
            "Plan Mode is enabled. Review this plan before write tools can execute."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        summary = QLabel(_summarise_plan(plan_text))
        summary.setWordWrap(True)
        summary.setStyleSheet("color:#334155;")
        layout.addWidget(summary)

        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(plan_text.strip() or "No plan content was produced.")
        details.setMinimumHeight(280)
        details.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(details)

        btn_box = QDialogButtonBox()
        approve_btn = btn_box.addButton("Approve Plan & Execute", QDialogButtonBox.AcceptRole)
        revise_btn = btn_box.addButton("Revise Plan", QDialogButtonBox.ActionRole)
        cancel_btn = btn_box.addButton("Cancel", QDialogButtonBox.RejectRole)

        approve_btn.setStyleSheet("background:#16a34a; color:white; font-weight:600;")
        revise_btn.setStyleSheet("background:#f59e0b; color:white; font-weight:600;")
        cancel_btn.setStyleSheet("background:#64748b; color:white; font-weight:600;")

        approve_btn.clicked.connect(self._approve)
        revise_btn.clicked.connect(self._revise)
        cancel_btn.clicked.connect(self.reject)

        layout.addWidget(btn_box)

    def _approve(self) -> None:
        self._decision = self.APPROVE_ROLE
        self.accept()

    def _revise(self) -> None:
        self._decision = self.REVISE_ROLE
        self.accept()


def _summarise_plan(plan_text: str) -> str:
    lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
    if not lines:
        return "No summary available."

    summary_lines = lines[:7]
    bullets = "\n".join(f"- {line}" for line in summary_lines)
    return f"Quick Summary:\n{bullets}"
