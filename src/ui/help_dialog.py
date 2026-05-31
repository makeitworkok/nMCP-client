# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Short in-app help covering quickstart and API key onboarding."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class HelpDialog(QDialog):
    """Display concise quickstart and API key guidance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("nMCP Client Help")
        self.setModal(True)
        self.setMinimumSize(700, 480)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(_make_panel(_quickstart_html()), "Quickstart")
        tabs.addTab(_make_panel(_api_key_html()), "API Keys")
        tabs.addTab(_make_panel(_troubleshooting_html()), "Troubleshooting")

        layout.addWidget(tabs)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)


def _make_panel(html: str) -> QWidget:
    panel = QTextBrowser()
    panel.setOpenExternalLinks(True)
    panel.setHtml(html)
    return panel


def _quickstart_html() -> str:
    return """
    <h3>Quickstart</h3>
    <ol>
      <li>Open <b>MCP Server</b> settings and enter your endpoint URL and credentials.</li>
      <li>Select an LLM provider and model, then add your provider API key.</li>
      <li>Click <b>Connect</b> and confirm tools appear in the Available Tools panel.</li>
      <li>Enable <b>Plan Mode</b> when you want to review and approve a plan before writes.</li>
      <li>Send your request in chat and approve write actions as needed.</li>
    </ol>
    """


def _api_key_html() -> str:
    return """
    <h3>Get Your Own API Key</h3>
    <p>Use provider portals to create your own key:</p>
    <ul>
      <li><b>OpenAI:</b> <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a></li>
      <li><b>Anthropic:</b> <a href='https://console.anthropic.com/settings/keys'>console.anthropic.com/settings/keys</a></li>
      <li><b>xAI:</b> <a href='https://console.x.ai/'>console.x.ai</a></li>
      <li><b>OpenRouter:</b> <a href='https://openrouter.ai/settings/keys'>openrouter.ai/settings/keys</a></li>
    </ul>
    <p><b>Security tips</b></p>
    <ul>
      <li>Never share API keys in chat logs or screenshots.</li>
      <li>Rotate keys immediately if you suspect exposure.</li>
      <li>Use the minimum permissions and budgets possible.</li>
    </ul>
    """


def _troubleshooting_html() -> str:
    return """
    <h3>Troubleshooting</h3>
    <ul>
      <li><b>Invalid API key:</b> re-paste the key and verify provider selection.</li>
      <li><b>Model errors:</b> use a model available to your account, then reconnect.</li>
      <li><b>MCP connection failures:</b> verify URL, credentials/token, and server reachability.</li>
      <li><b>Write blocked in Plan Mode:</b> approve the generated plan for this turn first.</li>
    </ul>
    """
