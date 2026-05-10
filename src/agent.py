# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Agentic loop — drives the LLM ↔ MCP conversation.

The loop runs inside the AsyncRunner's event loop and communicates with
the Qt main thread exclusively through Qt signals (thread-safe).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from src.llm.base import BaseLLMProvider, ToolCall
from src.mcp_client import NiagaraMCPClient
from src.safety import generate_explanation, is_write_tool

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a Niagara BAS (Building Automation System) assistant. "
    "You help users interact with a Niagara station through available MCP tools. "
    "When performing write operations, be precise and careful with component paths and values. "
    "Explain your reasoning briefly before each tool call. "
    "When the task is complete, give a concise summary to the user."
)

_MAX_ITERATIONS = 20  # safety cap to prevent infinite loops


class AgentSignals(QObject):
    """Signals emitted by the agent loop (may be emitted from asyncio thread)."""

    # Tool approval
    tool_approval_requested = Signal(str, str, str)  # tool_name, args_json, explanation

    # Progress
    tool_executed = Signal(str, str)  # tool_name, result_preview
    message_chunk = Signal(str)  # intermediate text (thinking, etc.)
    message_complete = Signal(str)  # final assistant answer

    # Status
    error_occurred = Signal(str)
    status_changed = Signal(str)


class AgentLoop:
    """Drives a single multi-turn LLM ↔ MCP conversation."""

    def __init__(
        self,
        mcp_client: NiagaraMCPClient,
        llm_provider: BaseLLMProvider,
    ) -> None:
        self._mcp = mcp_client
        self._llm = llm_provider
        self.signals = AgentSignals()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._approval_event: asyncio.Event | None = None
        self._approval_result: bool = False

    # ------------------------------------------------------------------
    # Thread-safe approval API (called from Qt main thread)
    # ------------------------------------------------------------------

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def resolve_approval(self, approved: bool) -> None:
        """Called from the Qt main thread after the user responds to an approval dialog."""
        self._approval_result = approved
        if self._loop and self._approval_event:
            self._loop.call_soon_threadsafe(self._approval_event.set)

    # ------------------------------------------------------------------
    # Main entry point (runs inside asyncio event loop)
    # ------------------------------------------------------------------

    async def run(self, user_message: str, tools: list[Any]) -> None:
        """Execute one user request end-to-end."""
        self._loop = asyncio.get_event_loop()
        self._llm.reset_conversation(_SYSTEM_PROMPT)
        self._llm.add_user_message(user_message)

        for iteration in range(_MAX_ITERATIONS):
            self.signals.status_changed.emit("Thinking…")
            logger.debug("Agent iteration %d", iteration + 1)

            try:
                response = await self._llm.get_response(tools)
            except Exception as exc:
                self.signals.error_occurred.emit(f"LLM error: {exc}")
                logger.exception("LLM error on iteration %d", iteration + 1)
                return

            # Emit any intermediate text alongside tool calls
            if response.content and response.tool_calls:
                self.signals.message_chunk.emit(response.content)

            # No tool calls → final answer
            if not response.tool_calls:
                self.signals.message_complete.emit(response.content or "")
                self.signals.status_changed.emit("Ready")
                return

            # Process tool calls; collect results to batch
            tool_results: list[tuple[str, str, str]] = []

            for tc in response.tool_calls:
                result_text = await self._execute_tool(tc)
                tool_results.append((tc.id, tc.name, result_text))

            # Feed all results back to the LLM in one shot
            self._llm.add_tool_results_batch(tool_results)

        self.signals.error_occurred.emit(
            "Reached the maximum number of iterations without a final answer."
        )
        self.signals.status_changed.emit("Ready")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_tool(self, tc: ToolCall) -> str:
        """Check safety, optionally request approval, then call the tool."""
        if is_write_tool(tc.name):
            explanation = generate_explanation(tc.name, tc.arguments)
            approved = await self._request_approval(tc.name, tc.arguments, explanation)
            if not approved:
                logger.info("Tool %s rejected by user", tc.name)
                return "Tool call rejected by user."

        self.signals.status_changed.emit(f"Executing {tc.name}…")
        logger.info("Calling tool %s  args=%s", tc.name, tc.arguments)

        try:
            raw_result = await self._mcp.call_tool(tc.name, tc.arguments)
            result_text = _format_tool_result(raw_result)
            preview = result_text[:300] + ("…" if len(result_text) > 300 else "")
            self.signals.tool_executed.emit(tc.name, preview)
            logger.info("Tool %s → %s", tc.name, result_text[:500])
            return result_text
        except Exception as exc:
            error = f"Tool execution error: {exc}"
            self.signals.status_changed.emit("Ready")
            self.signals.error_occurred.emit(error)
            logger.exception("Tool %s failed", tc.name)
            return error

    async def _request_approval(
        self, tool_name: str, arguments: dict[str, Any], explanation: str
    ) -> bool:
        """Pause the agent loop and ask the user for approval via Qt signal."""
        self._approval_event = asyncio.Event()
        args_json = json.dumps(arguments, indent=2, ensure_ascii=False)
        self.signals.tool_approval_requested.emit(tool_name, args_json, explanation)
        self.signals.status_changed.emit(f"Waiting for approval: {tool_name}…")
        await self._approval_event.wait()
        return self._approval_result


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _format_tool_result(result: Any) -> str:
    """Convert an MCP CallToolResult to a plain string."""
    if hasattr(result, "content"):
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif hasattr(block, "data"):
                parts.append(f"[binary data, {len(block.data)} bytes]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(result)
