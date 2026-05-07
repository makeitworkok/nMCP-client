"""Connection settings panel with LLM provider selection."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig

_PROVIDERS = ["openai", "anthropic", "xai", "ollama"]

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-opus-4-5",
    "xai": "grok-3",
    "ollama": "llama3.1",
}

_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "",
    "anthropic": "",
    "xai": "https://api.x.ai/v1",
    "ollama": "http://localhost:11434/v1",
}

_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "ollama": "",
}


class ConnectionWidget(QWidget):
    """Panel that collects MCP server URL + auth and LLM provider settings."""

    connect_requested = Signal(dict)    # emitted with a settings dict
    disconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_config(self, config: AppConfig) -> None:
        self._url_edit.setText(config.connection.mcp_url)
        self._station_edit.setText(config.connection.station_name)
        self._user_edit.setText(config.connection.username)
        self._pass_edit.setText(config.connection.password)
        self._token_edit.setText(config.connection.token)

        provider = config.llm.provider
        idx = self._provider_combo.findText(provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._model_edit.setText(config.llm.model)
        self._key_edit.setText(config.llm.api_key)
        self._base_url_edit.setText(config.llm.base_url)

    def set_connected(self, connected: bool) -> None:
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)

    def get_settings(self) -> dict:
        return {
            "mcp_url": self._url_edit.text().strip(),
            "station_name": self._station_edit.text().strip(),
            "username": self._user_edit.text().strip(),
            "password": self._pass_edit.text(),
            "token": self._token_edit.text().strip(),
            "provider": self._provider_combo.currentText(),
            "model": self._model_edit.text().strip(),
            "api_key": self._key_edit.text().strip(),
            "base_url": self._base_url_edit.text().strip(),
        }

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # ── MCP Server ──────────────────────────────────────────────
        mcp_group = QGroupBox("MCP Server")
        mcp_form = QFormLayout(mcp_group)
        mcp_form.setSpacing(4)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://host:8000/mcp")
        mcp_form.addRow("URL:", self._url_edit)

        self._station_edit = QLineEdit()
        self._station_edit.setPlaceholderText("MyStation")
        mcp_form.addRow("Station:", self._station_edit)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("admin")
        mcp_form.addRow("Username:", self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        mcp_form.addRow("Password:", self._pass_edit)

        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("Bearer token (overrides user/pass)")
        mcp_form.addRow("Token:", self._token_edit)

        root.addWidget(mcp_group)

        # ── LLM Provider ────────────────────────────────────────────
        llm_group = QGroupBox("LLM Provider")
        llm_form = QFormLayout(llm_group)
        llm_form.setSpacing(4)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(_PROVIDERS)
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        llm_form.addRow("Provider:", self._provider_combo)

        self._model_edit = QLineEdit()
        llm_form.addRow("Model:", self._model_edit)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.setPlaceholderText("API key")
        llm_form.addRow("API Key:", self._key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("optional base URL override")
        llm_form.addRow("Base URL:", self._base_url_edit)

        root.addWidget(llm_group)

        # ── Buttons ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self.disconnect_requested)

        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        root.addLayout(btn_row)
        root.addStretch()

        # Seed model/base-url for default provider
        self._on_provider_changed(self._provider_combo.currentText())

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_provider_changed(self, provider: str) -> None:
        if not self._model_edit.text():
            self._model_edit.setText(_DEFAULT_MODELS.get(provider, ""))
        if not self._base_url_edit.text():
            self._base_url_edit.setText(_DEFAULT_BASE_URLS.get(provider, ""))
        # Pre-fill API key from environment if available
        env_var = _ENV_KEYS.get(provider, "")
        if env_var and not self._key_edit.text():
            env_val = os.getenv(env_var, "")
            if env_val:
                self._key_edit.setText(env_val)

    def _on_connect_clicked(self) -> None:
        self.connect_requested.emit(self.get_settings())
