# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Main application window."""

from __future__ import annotations

import logging
import re
import traceback
from pathlib import Path
from typing import Literal
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMenu,
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
from src.memory import MemoryManager
from src.mcp_client import NiagaraMCPClient, build_headers
from src.ui.about_dialog import AboutDialog
from src.ui.approval_dialog import ApprovalDialog
from src.ui.chat_widget import ChatWidget
from src.ui.connection_widget import ConnectionWidget
from src.ui.help_dialog import HelpDialog
from src.ui.memory_health_widget import MemoryHealthWidget
from src.ui.plan_review_dialog import PlanReviewDialog
from src.ui.tools_widget import ToolsWidget

logger = logging.getLogger(__name__)

_APP_NAME = "nMCP Client"
_AUTHOR_NAME = "Chris Favre"
_REPO_URL = "https://github.com/makeitworkok/nMCP-client"


class _StatusLight(QLabel):
    """Small blinking circle in the status bar indicating connection/activity state."""

    _COLORS = {
        "disconnected": "#64748b",  # slate-gray
        "connected":    "#22c55e",  # green
        "busy":         "#f59e0b",  # amber
        "error":        "#ef4444",  # red
    }
    _COLORS_DIM = {
        "busy": "#78350f",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "disconnected"
        self._blink_on = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._blink)
        self.setFixedSize(14, 14)
        self._apply_style()

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "busy":
            self._timer.start(500)
        else:
            self._timer.stop()
            self._blink_on = True
        self._apply_style()

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self._apply_style()

    def _apply_style(self) -> None:
        if self._state == "busy" and not self._blink_on:
            color = self._COLORS_DIM.get("busy", "#78350f")
        else:
            color = self._COLORS.get(self._state, "#64748b")
        self.setStyleSheet(
            f"background:{color}; border-radius:7px; border:1px solid rgba(0,0,0,0.25);"
        )


def _format_exception_details(exc: Exception) -> str:
    """Build a useful error string for UI and logs."""
    message = str(exc).strip()
    if not message:
        message = repr(exc)

    return (
        f"{exc.__class__.__name__}: {message}\n"
        f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
    )


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

        if provider == "openrouter":
            from src.llm.openrouter_provider import OpenRouterProvider

            return OpenRouterProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or "https://openrouter.ai/api/v1",
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


def _load_project_version() -> str:
    """Read project version from pyproject.toml with a safe fallback."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', content, flags=re.MULTILINE)
        if match:
            return match.group(1)
    except Exception:
        logger.exception("Could not read version from pyproject.toml")
    return "0.0.0"


def _format_tool_result_to_text(result: Any) -> str:
    """Convert an MCP tool result object to plain text."""
    if hasattr(result, "content"):
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(str(block.text))
            elif hasattr(block, "data"):
                parts.append(f"[binary data, {len(block.data)} bytes]")
            else:
                parts.append(str(block))
        return "\n".join(parts).strip()
    return str(result).strip()


class MainWindow(QMainWindow):
    """Primary application window."""

    # ── Internal signals for thread-safe UI updates ──────────────────
    # These are emitted from asyncio callbacks (non-Qt thread) and
    # automatically queued to the main thread by PySide6.
    _sig_connected = Signal(list)       # tools list
    _sig_conn_error = Signal(str)       # error message
    _sig_agent_done = Signal()          # agent loop finished
    _sig_memory_health = Signal(object)
    _sig_conversations_loaded = Signal(list, str)
    _sig_conversation_history_loaded = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_APP_NAME)
        self.resize(1280, 820)
        self._status_state = "disconnected"

        self.setStyleSheet("""
            QMainWindow { background: #f1f5f9; }
            QGroupBox {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                margin-top: 10px;
                font-weight: 600;
                color: #1e293b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 16px;
                font-weight: 600;
            }
            QPushButton:hover    { background: #1d4ed8; }
            QPushButton:pressed  { background: #1e40af; }
            QPushButton:disabled { background: #94a3b8; color: #e2e8f0; }
            QLineEdit, QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 6px;
                background: white;
                selection-background-color: #bfdbfe;
            }
            QLineEdit:focus, QTextEdit:focus { border-color: #2563eb; }
            QComboBox {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 6px;
                background: white;
            }
            QComboBox:focus { border-color: #2563eb; }
            QListWidget {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background: white;
                alternate-background-color: #f8fafc;
            }
            QListWidget::item:selected {
                background: #2563eb;
                color: white;
            }
            QSplitter::handle { background: #cbd5e1; width: 2px; }
            QStatusBar {
                background: #1e293b;
                color: #e2e8f0;
                font-size: 12px;
            }
            QStatusBar QLabel { color: #e2e8f0; padding: 0 4px; }
        """)

        self._config: AppConfig = load_config()
        self._memory = MemoryManager.from_config(self._config)
        self._tools: list[Any] = []
        self._current_agent: AgentLoop | None = None
        self._pending_message: str | None = None
        self._last_assistant_message: str = ""
        self._active_conversation_id: str = ""
        self._agent_phase: Literal["idle", "planning", "executing"] = "idle"
        self._app_version = _load_project_version()

        # Async infrastructure
        self._async_runner = AsyncRunner()
        self._async_runner.start()
        self._mcp = NiagaraMCPClient()

        # Wire internal bridge signals
        self._sig_connected.connect(self._handle_connected)
        self._sig_conn_error.connect(self._handle_conn_error)
        self._sig_agent_done.connect(self._handle_agent_done)
        self._sig_memory_health.connect(self._on_memory_health_snapshot)
        self._sig_conversations_loaded.connect(self._on_conversations_loaded)
        self._sig_conversation_history_loaded.connect(self._on_conversation_history_loaded)

        self._build_ui()
        self._load_config_into_widgets()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

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
        self._memory_health_widget = MemoryHealthWidget()
        self._memory_health_widget.refresh_requested.connect(self._refresh_memory_health_ui)

        left_layout.addWidget(self._conn_widget)
        left_layout.addWidget(self._tools_widget, stretch=1)
        left_layout.addWidget(self._memory_health_widget)

        # Right panel — chat
        self._chat_widget = ChatWidget()
        self._chat_widget.message_submitted.connect(self._on_message_submitted)
        self._chat_widget.conversation_selected.connect(self._on_conversation_selected)
        self._chat_widget.conversation_create_requested.connect(self._on_new_conversation_requested)

        splitter.addWidget(left)
        splitter.addWidget(self._chat_widget)
        splitter.setSizes([380, 900])

        root_layout.addWidget(splitter)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # Left: blinking indicator light
        self._status_light = _StatusLight()
        status_bar.addWidget(self._status_light)

        # Left: status text (stretches)
        self._status_label = QLabel("Not connected")
        status_bar.addWidget(self._status_label, 1)

        # Right: attribution (permanent = right-aligned, never covered by showMessage)
        attribution = QLabel("Created by makeitworkok (Chris Favre)")
        attribution.setStyleSheet("color:#94a3b8; font-size:11px; padding-right:6px;")
        status_bar.addPermanentWidget(attribution)

        self._set_status("Not connected", "disconnected")
        self._refresh_memory_health_ui()
        self._initialize_conversations_ui()

    def _build_menu(self) -> None:
        help_menu: QMenu = self.menuBar().addMenu("Help")

        quick_help_action = QAction("Quick Help", self)
        quick_help_action.triggered.connect(self._show_help_dialog)
        help_menu.addAction(quick_help_action)

        about_action = QAction("About nMCP Client", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _set_status(self, text: str, state: str) -> None:
        """Update status label text and the indicator light state."""
        self._status_state = state
        self._status_label.setText(text)
        self._status_light.set_state(state)

    def _on_agent_status_changed(self, text: str) -> None:
        """Translate agent status text → indicator state."""
        if text.startswith(("Thinking", "Executing", "Waiting")):
            self._set_status(text, "busy")
        else:
            self._set_status(f"Connected  |  {len(self._tools)} tools", "connected")

    def _load_config_into_widgets(self) -> None:
        self._conn_widget.load_config(self._config)
        self._chat_widget.load_config(self._config)

    @Slot(object)
    def _on_memory_health_snapshot(self, snapshot: object) -> None:
        self._memory_health_widget.set_snapshot(snapshot)

    def _refresh_memory_health_ui(self) -> None:
        snapshot = self._memory.get_health_snapshot()
        self._memory_health_widget.set_snapshot(snapshot)

    def _initialize_conversations_ui(self) -> None:
        station = self._config.connection.station_name
        endpoint = self._config.connection.mcp_url
        thread = self._memory.ensure_default_conversation(station, endpoint)
        self._active_conversation_id = thread.conversation_id
        self._load_conversations_ui()
        self._load_active_conversation_history()

    def _load_conversations_ui(self) -> None:
        station = self._config.connection.station_name
        endpoint = self._mcp.endpoint_url or self._config.connection.mcp_url
        threads = self._memory.list_conversations(station, endpoint)
        items = [(t.conversation_id, t.title) for t in threads]
        self._sig_conversations_loaded.emit(items, self._active_conversation_id)

    def _load_active_conversation_history(self) -> None:
        if not self._active_conversation_id:
            return
        messages = self._memory.get_conversation_messages(self._active_conversation_id)
        payload = [(m.role, m.content) for m in messages]
        self._sig_conversation_history_loaded.emit(payload)

    @Slot(list, str)
    def _on_conversations_loaded(self, items: list, active_id: str) -> None:
        normalized = [(str(item[0]), str(item[1])) for item in items]
        self._chat_widget.set_conversations(normalized, active_id)

    @Slot(list)
    def _on_conversation_history_loaded(self, messages: list) -> None:
        normalized = [(str(item[0]), str(item[1])) for item in messages]
        self._chat_widget.load_history(normalized)

    @Slot(str)
    def _on_conversation_selected(self, conversation_id: str) -> None:
        if not conversation_id or conversation_id == self._active_conversation_id:
            return
        self._active_conversation_id = conversation_id
        self._load_active_conversation_history()

    @Slot()
    def _on_new_conversation_requested(self) -> None:
        station = self._config.connection.station_name
        endpoint = self._mcp.endpoint_url or self._config.connection.mcp_url
        thread = self._memory.create_conversation(station, endpoint)
        self._active_conversation_id = thread.conversation_id
        self._load_conversations_ui()
        self._load_active_conversation_history()

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
        self._initialize_conversations_ui()

        headers = build_headers(
            username=c.username,
            password=c.password,
            token=c.token,
        )

        self._set_status("Connecting…", "busy")
        self._chat_widget.append_system_message(f"Connecting to {c.mcp_url}…")

        future = self._async_runner.submit(
            self._mcp.connect(
                c.mcp_url,
                headers,
                username=c.username,
                password=c.password,
                token=c.token,
            )
        )
        future.add_done_callback(self._cb_after_connect)

    def _cb_after_connect(self, future) -> None:
        """Callback runs in asyncio thread — use signals to reach main thread."""
        try:
            future.result()
        except Exception as exc:
            details = _format_exception_details(exc)
            logger.error("Connection setup failed\n%s", details)
            self._sig_conn_error.emit(details)
            return
        tools_future = self._async_runner.submit(self._mcp.list_tools())
        tools_future.add_done_callback(self._cb_after_list_tools)

    def _cb_after_list_tools(self, future) -> None:
        """Callback runs in asyncio thread."""
        try:
            tools = future.result()
            self._sig_connected.emit(tools)
        except Exception as exc:
            details = _format_exception_details(exc)
            logger.error("Tool discovery failed\n%s", details)
            self._sig_conn_error.emit(details)

    @Slot(list)
    def _handle_connected(self, tools: list) -> None:
        """Runs in Qt main thread."""
        self._tools = tools
        self._tools_widget.set_tools(tools)
        self._conn_widget.set_connected(True)
        connected_url = self._mcp.endpoint_url or self._config.connection.mcp_url
        self._chat_widget.append_system_message(
            f"✅ Connected. {len(tools)} tool(s) available."
        )
        self._set_status(
            f"Connected to {connected_url}  |  {len(tools)} tools",
            "connected",
        )
        logger.info("Connected — %d tools", len(tools))

        if self._memory.enabled:
            profile_future = self._async_runner.submit(self._refresh_station_profile())
            profile_future.add_done_callback(self._cb_after_station_profile_refresh)
        self._refresh_memory_health_ui()

    async def _refresh_station_profile(self) -> None:
        """Fetch station.info and persist a lightweight local station profile."""
        station_info_result = await self._mcp.call_tool("nmcp.station.info", {})
        station_info_text = _format_tool_result_to_text(station_info_result)
        self._memory.update_station_profile(
            station_name=self._config.connection.station_name,
            endpoint_url=self._mcp.endpoint_url or self._config.connection.mcp_url,
            station_info_text=station_info_text,
        )

    def _cb_after_station_profile_refresh(self, future) -> None:
        """Log station profile refresh outcomes without interrupting the user flow."""
        try:
            future.result()
            logger.info("Memory station profile refreshed")
            self._sig_memory_health.emit(self._memory.get_health_snapshot())
        except Exception as exc:
            logger.warning("Could not refresh memory station profile: %s", exc)
            self._sig_memory_health.emit(self._memory.get_health_snapshot())

    @Slot(str)
    def _handle_conn_error(self, error: str) -> None:
        """Runs in Qt main thread."""
        self._chat_widget.append_error_message(f"Connection failed: {error}")
        self._set_status("Connection failed", "error")
        logger.error("Connection error details\n%s", error)

    @Slot()
    def _on_disconnect_requested(self) -> None:
        future = self._async_runner.submit(self._mcp.disconnect())
        future.add_done_callback(lambda _f: None)
        self._tools = []
        self._tools_widget.clear_tools()
        self._conn_widget.set_connected(False)
        self._chat_widget.append_system_message("Disconnected.")
        self._set_status("Not connected", "disconnected")
        self._refresh_memory_health_ui()

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

        self._chat_widget.append_user_message(message)
        self._pending_message = message
        self._persist_chat_message("user", message)

        if self._chat_widget.is_plan_mode_enabled():
            self._chat_widget.append_system_message(
                "Plan Mode enabled: generating plan before execution."
            )
            self._agent_phase = "planning"
            self._start_agent_run(
                message=message,
                tools=[],
                planning_mode=True,
                writes_permitted=False,
                strict_paths=self._chat_widget.is_strict_paths_enabled(),
            )
            return

        self._agent_phase = "executing"
        self._start_agent_run(
            message=message,
            tools=self._tools,
            planning_mode=False,
            writes_permitted=True,
            strict_paths=self._chat_widget.is_strict_paths_enabled(),
            provider=provider,
        )

    def _start_agent_run(
        self,
        message: str,
        tools: list[Any],
        planning_mode: bool,
        writes_permitted: bool,
        strict_paths: bool = True,
        provider: BaseLLMProvider | None = None,
    ) -> None:
        active_provider = provider or _create_llm_provider(self._config)
        if active_provider is None:
            self._chat_widget.append_error_message(
                "Could not create LLM provider. Check your provider settings and API key."
            )
            self._agent_phase = "idle"
            self._chat_widget.enable_input()
            return

        agent = AgentLoop(
            self._mcp,
            active_provider,
            planning_mode=planning_mode,
            writes_permitted=writes_permitted,
            strict_paths=strict_paths,
            memory_context=self._memory.build_prompt_context(
                user_message=message,
                station_name=self._config.connection.station_name,
                endpoint_url=self._mcp.endpoint_url or self._config.connection.mcp_url,
            )
            + "\n\n"
            + self._memory.build_conversation_context(self._active_conversation_id),
            tool_observer=self._observe_tool_outcome,
        )
        agent.set_event_loop(self._async_runner.get_loop())
        self._current_agent = agent

        sigs = agent.signals
        sigs.tool_approval_requested.connect(self._on_approval_requested)
        sigs.tool_executed.connect(self._on_tool_executed)
        sigs.message_chunk.connect(self._chat_widget.append_assistant_chunk)
        sigs.message_complete.connect(self._on_message_complete)
        sigs.error_occurred.connect(self._on_agent_error)
        sigs.status_changed.connect(self._on_agent_status_changed)

        future = self._async_runner.submit(agent.run(message, tools))
        future.add_done_callback(lambda _f: self._sig_agent_done.emit())

    def _observe_tool_outcome(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> None:
        """Capture repeatable lessons and working-folder context from tool activity."""
        try:
            self._memory.learn_from_tool_result(
                station_name=self._config.connection.station_name,
                endpoint_url=self._mcp.endpoint_url or self._config.connection.mcp_url,
                tool_name=tool_name,
                arguments=arguments,
                result_text=result_text,
            )
            self._sig_memory_health.emit(self._memory.get_health_snapshot())
        except Exception as exc:
            logger.warning("Could not learn from tool outcome for %s: %s", tool_name, exc)

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
        self._persist_chat_message("tool", f"{tool_name}: {result_preview}")

    @Slot(str)
    def _on_message_complete(self, text: str) -> None:
        self._last_assistant_message = text
        self._chat_widget.complete_assistant_message(text)
        self._persist_chat_message("assistant", text)

    @Slot(str)
    def _on_agent_error(self, error: str) -> None:
        self._chat_widget.append_error_message(error)
        self._persist_chat_message("error", error)

    @Slot()
    def _handle_agent_done(self) -> None:
        if self._agent_phase == "planning":
            self._handle_plan_review()
            return

        self._agent_phase = "idle"
        self._pending_message = None
        self._chat_widget.enable_input()
        if self._status_state == "busy":
            self._set_status(f"Connected  |  {len(self._tools)} tools", "connected")

    def _handle_plan_review(self) -> None:
        dialog = PlanReviewDialog(self._last_assistant_message, self)
        accepted = dialog.exec() == QDialog.Accepted

        if accepted and dialog.decision == PlanReviewDialog.APPROVE_ROLE:
            if not self._pending_message:
                self._chat_widget.append_error_message(
                    "Could not execute approved plan because the message context is missing."
                )
                self._agent_phase = "idle"
                self._chat_widget.enable_input()
                return
            self._chat_widget.append_system_message(
                "Plan approved. Executing request with write tools enabled for this turn."
            )
            # Build an execution message that includes the approved plan so the agent
            # knows exactly what to do without re-planning or asking for confirmation.
            execution_message = (
                f"{self._pending_message}\n\n"
                f"[APPROVED PLAN — EXECUTE NOW]\n"
                f"The user has reviewed and approved the following plan. "
                f"Execute every step in it immediately using the available tools. "
                f"Do not re-plan, do not summarise the plan again, do not ask for "
                f"confirmation. Proceed directly with tool calls.\n\n"
                f"{self._last_assistant_message}"
            )
            self._agent_phase = "executing"
            self._start_agent_run(
                message=execution_message,
                tools=self._tools,
                planning_mode=False,
                writes_permitted=True,
                strict_paths=self._chat_widget.is_strict_paths_enabled(),
            )
            return

        self._agent_phase = "idle"
        self._pending_message = None
        if accepted and dialog.decision == PlanReviewDialog.REVISE_ROLE:
            self._chat_widget.append_system_message(
                "Plan not approved. Revise your request and send again."
            )
        else:
            self._chat_widget.append_system_message("Plan execution cancelled.")
        self._chat_widget.enable_input()
        if self._status_state == "busy":
            self._set_status(f"Connected  |  {len(self._tools)} tools", "connected")

    def _show_about_dialog(self) -> None:
        dialog = AboutDialog(
            app_name=_APP_NAME,
            version=self._app_version,
            author_name=_AUTHOR_NAME,
            repo_url=_REPO_URL,
            parent=self,
        )
        dialog.exec()

    def _show_help_dialog(self) -> None:
        dialog = HelpDialog(self)
        dialog.exec()

    def _persist_chat_message(self, role: str, content: str) -> None:
        if not self._active_conversation_id:
            return
        try:
            self._memory.append_conversation_message(
                conversation_id=self._active_conversation_id,
                role=role,
                content=content,
            )
            self._load_conversations_ui()
            self._sig_memory_health.emit(self._memory.get_health_snapshot())
        except Exception as exc:
            logger.warning("Could not persist chat message (%s): %s", role, exc)

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
