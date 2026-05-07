"""Main application window."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig, load_config, save_config
from src.agent import AgentLoop
from src.async_runner import AsyncRunner
from src.llm.base import BaseLLMProvider
from src.mcp_client import NiagaraMCPClient, build_headers
from src.ui.approval_dialog import ApprovalDialog
from src.ui.chat_widget import ChatWidget
from src.ui.connection_widget import ConnectionWidget
from src.ui.tools_widget import ToolsWidget

logger = logging.getLogger(__name__)


def _create_llm_provider(config: AppConfig) -> BaseLLMProvider | None:
    """Instantiate the appropriate LLM provider from config."""
    provider = config.llm.provider
    model = config.llm.model
    api_key = config.llm.api_key
    base_url = config.llm.base_url or None

    try:
        if provider == "openai":
            from src.llm.openai_provider import OpenAIProvider

            return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

        if provider == "anthropic":
            from src.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(api_key=api_key, model=model)

        if provider == "xai":
            from src.llm.xai_provider import XAIProvider

            return XAIProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or "https://api.x.ai/v1",
            )

        if provider == "ollama":
            from src.llm.ollama_provider import OllamaProvider

            return OllamaProvider(
                model=model,
                base_url=base_url or "http://localhost:11434/v1",
            )

    except Exception as exc:
        logger.error("Failed to create LLM provider %s: %s", provider, exc)

    return None


class MainWindow(QMainWindow):
    """Primary application window."""

    # ── Internal signals for thread-safe UI updates ──────────────────
    # These are emitted from asyncio callbacks (non-Qt thread) and
    # automatically queued to the main thread by PySide6.
    _sig_connected = Signal(list)       # tools list
    _sig_conn_error = Signal(str)       # error message
    _sig_agent_done = Signal()          # agent loop finished

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("nMCP Client — Niagara MCP Client")
        self.resize(1280, 820)

        self._config: AppConfig = load_config()
        self._tools: list[Any] = []
        self._current_agent: AgentLoop | None = None

        # Async infrastructure
        self._async_runner = AsyncRunner()
        self._async_runner.start()
        self._mcp = NiagaraMCPClient()

        # Wire internal bridge signals
        self._sig_connected.connect(self._handle_connected)
        self._sig_conn_error.connect(self._handle_conn_error)
        self._sig_agent_done.connect(self._handle_agent_done)

        self._build_ui()
        self._load_config_into_widgets()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # Left panel — connection + tools
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)

        self._conn_widget = ConnectionWidget()
        self._conn_widget.connect_requested.connect(self._on_connect_requested)
        self._conn_widget.disconnect_requested.connect(self._on_disconnect_requested)

        self._tools_widget = ToolsWidget()

        left_layout.addWidget(self._conn_widget)
        left_layout.addWidget(self._tools_widget, stretch=1)

        # Right panel — chat
        self._chat_widget = ChatWidget()
        self._chat_widget.message_submitted.connect(self._on_message_submitted)

        splitter.addWidget(left)
        splitter.addWidget(self._chat_widget)
        splitter.setSizes([380, 900])

        root_layout.addWidget(splitter)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("Not connected")

    def _load_config_into_widgets(self) -> None:
        self._conn_widget.load_config(self._config)
        self._chat_widget.load_config(self._config)

    # ------------------------------------------------------------------
    # Slots — connection
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_connect_requested(self, settings: dict) -> None:
        # Persist settings
        c = self._config.connection
        c.mcp_url = settings["mcp_url"]
        c.station_name = settings.get("station_name", "")
        c.username = settings.get("username", "")
        c.password = settings.get("password", "")
        c.token = settings.get("token", "")

        l = self._config.llm
        l.provider = settings["provider"]
        l.model = settings["model"]
        l.api_key = settings.get("api_key", "")
        l.base_url = settings.get("base_url", "")

        save_config(self._config)

        headers = build_headers(
            username=c.username,
            password=c.password,
            token=c.token,
        )

        self.statusBar().showMessage("Connecting…")
        self._chat_widget.append_system_message(f"Connecting to {c.mcp_url}…")

        future = self._async_runner.submit(
            self._mcp.connect(c.mcp_url, headers)
        )
        future.add_done_callback(self._cb_after_connect)

    def _cb_after_connect(self, future) -> None:
        """Callback runs in asyncio thread — use signals to reach main thread."""
        try:
            future.result()
        except Exception as exc:
            self._sig_conn_error.emit(str(exc))
            return
        tools_future = self._async_runner.submit(self._mcp.list_tools())
        tools_future.add_done_callback(self._cb_after_list_tools)

    def _cb_after_list_tools(self, future) -> None:
        """Callback runs in asyncio thread."""
        try:
            tools = future.result()
            self._sig_connected.emit(tools)
        except Exception as exc:
            self._sig_conn_error.emit(str(exc))

    @Slot(list)
    def _handle_connected(self, tools: list) -> None:
        """Runs in Qt main thread."""
        self._tools = tools
        self._tools_widget.set_tools(tools)
        self._conn_widget.set_connected(True)
        self._chat_widget.append_system_message(
            f"✅ Connected. {len(tools)} tool(s) available."
        )
        self.statusBar().showMessage(
            f"Connected to {self._config.connection.mcp_url}  |  {len(tools)} tools"
        )
        logger.info("Connected — %d tools", len(tools))

    @Slot(str)
    def _handle_conn_error(self, error: str) -> None:
        """Runs in Qt main thread."""
        self._chat_widget.append_error_message(f"Connection failed: {error}")
        self.statusBar().showMessage("Connection failed")
        logger.error("Connection error: %s", error)

    @Slot()
    def _on_disconnect_requested(self) -> None:
        future = self._async_runner.submit(self._mcp.disconnect())
        future.add_done_callback(lambda _f: None)
        self._tools = []
        self._tools_widget.clear_tools()
        self._conn_widget.set_connected(False)
        self._chat_widget.append_system_message("Disconnected.")
        self.statusBar().showMessage("Not connected")

    # ------------------------------------------------------------------
    # Slots — chat
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_message_submitted(self, message: str) -> None:
        if not self._tools:
            self._chat_widget.append_system_message(
                "Please connect to an MCP server first."
            )
            self._chat_widget.enable_input()
            return

        provider = _create_llm_provider(self._config)
        if provider is None:
            self._chat_widget.append_error_message(
                "Could not create LLM provider. Check your provider settings and API key."
            )
            self._chat_widget.enable_input()
            return

        agent = AgentLoop(self._mcp, provider)
        agent.set_event_loop(self._async_runner.get_loop())
        self._current_agent = agent

        sigs = agent.signals
        sigs.tool_approval_requested.connect(self._on_approval_requested)
        sigs.tool_executed.connect(self._on_tool_executed)
        sigs.message_chunk.connect(self._chat_widget.append_assistant_chunk)
        sigs.message_complete.connect(self._on_message_complete)
        sigs.error_occurred.connect(self._on_agent_error)
        sigs.status_changed.connect(self.statusBar().showMessage)

        future = self._async_runner.submit(agent.run(message, self._tools))
        future.add_done_callback(lambda _f: self._sig_agent_done.emit())

    @Slot(str, str, str)
    def _on_approval_requested(
        self, tool_name: str, args_json: str, explanation: str
    ) -> None:
        dialog = ApprovalDialog(tool_name, args_json, explanation, self)
        approved = dialog.exec() == QDialog.Accepted
        if self._current_agent:
            self._current_agent.resolve_approval(approved)

    @Slot(str, str)
    def _on_tool_executed(self, tool_name: str, result_preview: str) -> None:
        self._chat_widget.append_tool_result(tool_name, result_preview)

    @Slot(str)
    def _on_message_complete(self, text: str) -> None:
        self._chat_widget.complete_assistant_message(text)

    @Slot(str)
    def _on_agent_error(self, error: str) -> None:
        self._chat_widget.append_error_message(error)

    @Slot()
    def _handle_agent_done(self) -> None:
        self._chat_widget.enable_input()
        if self.statusBar().currentMessage().startswith(
            ("Thinking", "Executing", "Waiting")
        ):
            self.statusBar().showMessage(
                f"Connected  |  {len(self._tools)} tools"
            )

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        save_config(self._config)
        future = self._async_runner.submit(self._mcp.disconnect())
        try:
            future.result(timeout=2)
        except Exception:
            pass
        self._async_runner.stop()
        self._async_runner.wait(3000)
        super().closeEvent(event)
