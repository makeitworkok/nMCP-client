# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Agentic loop — drives the LLM ↔ MCP conversation.

The loop runs inside the AsyncRunner's event loop and communicates with
the Qt main thread exclusively through Qt signals (thread-safe).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from src.llm.base import BaseLLMProvider, ToolCall
from src.mcp_client import NiagaraMCPClient
from src.safety import generate_explanation, is_write_tool

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a Niagara BAS (Building Automation System) assistant. "
    "You help users interact with a Niagara station through available MCP tools. "
    "\n\n"
    "PATH RULES:\n"
    "1. If the user explicitly provides a full component path (e.g. "
    "   'local:|foxwss:|station:|slot:/Drivers/sandbox'), use it DIRECTLY in tool calls. "
    "   Do NOT attempt root discovery first — trust the user-supplied path.\n"
    "2. If no path is given and you need to construct one, call nmcp.component.children "
    "   with the deepest known ancestor to navigate to the target.\n"
    "3. Do NOT guess or invent paths. If you have no path at all and the user did not "
    "   provide one, ask the user for the correct base path before making tool calls.\n"
    "4. If nmcp.component.children returns 'Path not in allowlisted roots', do NOT retry "
    "   the same call. Instead ask the user: 'Please provide the exact path — the server's "
    "   allowlist blocks automatic discovery.' Then wait for their answer.\n"
    "\n"
    "AUTONOMY RULES:\n"
    "1. If the user gives a valid path and asks for a concrete action, execute it without "
    "   unnecessary follow-up questions.\n"
    "2. For requests like 'set proper facets/units/defaults' on a folder, first enumerate "
    "   children, infer standard BAS defaults from point names/types, and proceed. "
    "   Ask questions only when required data is truly missing.\n"
    "3. For 'examine/tell me about logic' requests on a folder, inspect child components "
    "   and links, then provide a concrete summary of the implemented logic.\n"
    "\n"
    "WIRESHEET RULES:\n"
    "**Sequencing Rule:** Always create all points/components first, then add logic blocks (e.g., control, math, compare), then wire/link last. Never attempt to wire or configure logic for components that do not exist yet.\n"
    "1. Every operation object MUST include a 'type' field "
    "   (createComponent | setSlot | link | addCompositePin).\n"
    "2. Always run nmcp.wiresheet.plan before nmcp.wiresheet.apply.\n"
    "3. For type=setSlot operations, ALWAYS include componentOrd, slot, and value.\n"
    "4. For type=setSlot operations, componentOrd MUST be an absolute component ORD under "
    "   an allowlisted root.\n"
    "5. For facet updates, write slot='facets' as a whole value; do NOT write nested "
    "   facet sub-slots like facets.units.\n"
    "6. For type=link operations, ALWAYS include both 'from' and 'to'.\n"
    "7. For type=link operations, 'from' and 'to' MUST be absolute slot endpoints "
    "   under an allowlisted root (never bare tokens like out, inA, or out/out).\n"
    "\n"
    "When performing write operations, be precise and careful with component paths and values. "
    "Explain your reasoning briefly before each tool call. "
    "When the task is complete, give a concise summary to the user."
)

_MAX_ITERATIONS = 20  # safety cap to prevent infinite loops
_LLM_RATE_LIMIT_MAX_RETRIES = 3
_MAX_TOOL_RESULT_CHARS = 8000
_WIRESHEET_OPERATION_TYPES = {
    "createComponent",
    "setSlot",
    "link",
    "addCompositePin",
}


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
        planning_mode: bool = False,
        writes_permitted: bool = True,
        strict_paths: bool = True,
        memory_context: str = "",
        tool_observer: Callable[[str, dict[str, Any], str], None] | None = None,
    ) -> None:
        self._mcp = mcp_client
        self._llm = llm_provider
        self._planning_mode = planning_mode
        self._writes_permitted = writes_permitted
        self._strict_paths = strict_paths
        self._memory_context = memory_context.strip()
        self._tool_observer = tool_observer
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
        system_prompt = _SYSTEM_PROMPT
        if self._memory_context:
            system_prompt += "\n\n" + self._memory_context
        if self._planning_mode:
            system_prompt += (
                " You are currently in PLAN MODE. Do not execute tools. "
                "Respond with a short checklist (3-7 steps) followed by a detailed "
                "preview of proposed tool calls and key risks."
            )
        if not self._strict_paths:
            system_prompt += (
                "\n\nPATH ASSUMPTION MODE is active. You MAY infer reasonable Niagara ORD "
                "paths from context clues in the user's message (e.g. if the user says "
                "'sandbox folder', try station:|slot:/Drivers/sandbox or the most likely "
                "equivalent based on standard Niagara station layout). "
                "Always state the path you are assuming before making the tool call. "
                "If the inferred path returns an error, report it and ask the user to "
                "confirm the exact path before retrying."
            )

        self._llm.reset_conversation(system_prompt)
        self._llm.add_user_message(user_message)

        for iteration in range(_MAX_ITERATIONS):
            self.signals.status_changed.emit("Thinking…")
            logger.debug("Agent iteration %d", iteration + 1)

            response = None
            for attempt in range(_LLM_RATE_LIMIT_MAX_RETRIES + 1):
                try:
                    response = await self._llm.get_response(tools)
                    break
                except Exception as exc:
                    wait_seconds = _parse_rate_limit_wait_seconds(str(exc))
                    is_last_attempt = attempt >= _LLM_RATE_LIMIT_MAX_RETRIES
                    if wait_seconds is None or is_last_attempt:
                        self.signals.error_occurred.emit(f"LLM error: {exc}")
                        logger.exception("LLM error on iteration %d", iteration + 1)
                        return

                    wait_seconds = min(max(wait_seconds, 0.5), 12.0)
                    self.signals.status_changed.emit(
                        f"Rate limited by provider; retrying in {wait_seconds:.1f}s…"
                    )
                    logger.warning(
                        "Rate limited on iteration %d, attempt %d/%d. Retrying in %.2fs",
                        iteration + 1,
                        attempt + 1,
                        _LLM_RATE_LIMIT_MAX_RETRIES + 1,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)

            if response is None:
                self.signals.error_occurred.emit("LLM error: no response returned.")
                self.signals.status_changed.emit("Ready")
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
        wiresheet_error = _validate_wiresheet_payload(tc.name, tc.arguments)
        if wiresheet_error:
            logger.warning("Blocked invalid wiresheet payload: %s", wiresheet_error)
            return wiresheet_error

        if is_write_tool(tc.name) and not self._writes_permitted:
            logger.info("Blocked write tool %s because writes are not permitted", tc.name)
            return (
                "Write action blocked: this turn is in plan-only mode. "
                "Approve the plan before executing write tools."
            )

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
            result_text = _augment_path_error(result_text, tc.arguments)
            result_text = _balance_tool_result_text(result_text)
            if self._tool_observer:
                try:
                    self._tool_observer(tc.name, tc.arguments, result_text)
                except Exception as obs_exc:
                    logger.warning("Tool observer failed for %s: %s", tc.name, obs_exc)
            preview = result_text[:300] + ("…" if len(result_text) > 300 else "")
            self.signals.tool_executed.emit(tc.name, preview)
            logger.info("Tool %s → %s", tc.name, result_text[:500])
            return result_text
        except Exception as exc:
            error = f"Tool execution error: {exc}"
            if self._tool_observer:
                try:
                    self._tool_observer(tc.name, tc.arguments, error)
                except Exception as obs_exc:
                    logger.warning("Tool observer failed for %s: %s", tc.name, obs_exc)
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


_ROOT_DISCOVERY_PATHS = [
    "station:|slot:/",
]

_RATE_LIMIT_WAIT_PATTERN = re.compile(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


def _parse_rate_limit_wait_seconds(error_text: str) -> float | None:
    """Extract provider-suggested retry delay (seconds) from a rate-limit message."""
    lowered = error_text.lower()
    if "rate limit" not in lowered and "429" not in lowered:
        return None

    match = _RATE_LIMIT_WAIT_PATTERN.search(error_text)
    if not match:
        return 2.0

    try:
        return float(match.group(1))
    except ValueError:
        return 2.0


def _balance_tool_result_text(result_text: str) -> str:
    """Cap tool result size before feeding it back to the LLM to reduce TPM spikes."""
    if len(result_text) <= _MAX_TOOL_RESULT_CHARS:
        return result_text

    head_len = 5000
    tail_len = 2200
    omitted = len(result_text) - head_len - tail_len
    if omitted < 0:
        omitted = len(result_text) - _MAX_TOOL_RESULT_CHARS

    head = result_text[:head_len].rstrip()
    tail = result_text[-tail_len:].lstrip()
    return (
        f"{head}\n\n"
        f"[TRUNCATED TOOL RESULT: omitted {omitted} characters to control token usage. "
        f"If you need more detail, call the tool again with tighter filters/limits.]\n\n"
        f"{tail}"
    )


def _augment_path_error(result_text: str, tool_args: dict[str, Any] | None = None) -> str:
    """Append a discovery hint when the server returns a path-not-allowlisted error."""
    if "NMCP_PATH_NOT_ALLOWLISTED" not in result_text and "Path not in allowlisted roots" not in result_text:
        return result_text

    # Detect if the call that failed was itself a root-discovery attempt.
    # If so, the server's allowlist blocks even root enumeration — ask the user.
    if tool_args is not None:
        ord_val = tool_args.get("ord", "")
        if ord_val in _ROOT_DISCOVERY_PATHS:
            hint = (
                "\n\n[AGENT HINT] Root path discovery is blocked by the server's allowlist. "
                "Do NOT retry component.children on the root path. "
                "Ask the user: 'Please provide the exact base path (e.g. "
                "station:|slot:/Drivers/sandbox) — the server blocks automatic discovery.' "
                "Wait for their answer before making any further tool calls."
            )
            return result_text + hint

    hint = (
        "\n\n[AGENT HINT] The path you used is not in the server's allowlisted roots. "
        "Call nmcp.component.children with ord='station:|slot:/' to discover valid top-level "
        "paths, then repeat the operation using an allowlisted path."
    )
    return result_text + hint


def _is_absolute_slot_endpoint(value: Any) -> bool:
    """Return True when value looks like an absolute Niagara slot endpoint."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    # We only enforce the absolute ORD marker here; allowlist and slot existence are server-validated.
    if ":|slot:/" not in text:
        return False
    # Reject common malformed shorthand values seen in failures.
    lowered = text.lower()
    if lowered in {"out", "in", "ina", "inb", "out/out"}:
        return False
    return True


def _is_absolute_component_ord(value: Any) -> bool:
    """Return True when value looks like an absolute Niagara component ORD."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    return ":|slot:/" in text


def _validate_wiresheet_payload(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Validate wiresheet payload shape before calling the MCP server."""
    if tool_name not in {
        "nmcp.wiresheet.apply",
        "nmcp.wiresheet.plan",
        "nmcp.wiresheet.diff",
    }:
        return None

    operations = arguments.get("operations")
    if not isinstance(operations, list) or not operations:
        return None

    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            return f"Invalid wiresheet payload: operation at index {idx} must be an object."
        op_type = op.get("type")
        if op_type not in _WIRESHEET_OPERATION_TYPES:
            return (
                "Invalid wiresheet payload: each operation must include a valid 'type' "
                "(createComponent, setSlot, link, addCompositePin). "
                f"Operation index {idx} has type={op_type!r}."
            )

        if op_type == "setSlot":
            component_ord = op.get("componentOrd")
            slot_name = op.get("slot")

            if not component_ord:
                return (
                    "Invalid wiresheet payload: setSlot operations require non-empty "
                    "'componentOrd', 'slot', and 'value' fields. "
                    f"Operation index {idx} is missing 'componentOrd'."
                )
            if not _is_absolute_component_ord(component_ord):
                return (
                    "Invalid wiresheet payload: setSlot 'componentOrd' must be an absolute "
                    "component ORD under an allowlisted root. "
                    f"Operation index {idx} has componentOrd={component_ord!r}."
                )
            if not isinstance(slot_name, str) or not slot_name.strip():
                return (
                    "Invalid wiresheet payload: setSlot operations require non-empty "
                    "'componentOrd', 'slot', and 'value' fields. "
                    f"Operation index {idx} is missing 'slot'."
                )
            if slot_name.startswith("facets."):
                return (
                    "Invalid wiresheet payload: nested facet sub-slots are not supported for "
                    "setSlot in this environment. Use slot='facets' and provide the full facets "
                    f"value. Operation index {idx} has slot={slot_name!r}."
                )
            if "value" not in op:
                return (
                    "Invalid wiresheet payload: setSlot operations require non-empty "
                    "'componentOrd', 'slot', and 'value' fields. "
                    f"Operation index {idx} is missing 'value'."
                )

        if op_type == "link":
            from_value = op.get("from")
            to_value = op.get("to")

            if not from_value:
                return (
                    "Invalid wiresheet payload: link operations require non-empty 'from' and 'to' fields. "
                    f"Operation index {idx} is missing 'from'."
                )
            if not to_value:
                return (
                    "Invalid wiresheet payload: link operations require non-empty 'from' and 'to' fields. "
                    f"Operation index {idx} is missing 'to'."
                )
            if not _is_absolute_slot_endpoint(from_value):
                return (
                    "Invalid wiresheet payload: link 'from' must be an absolute slot endpoint under "
                    "an allowlisted root (not shorthand like out/inA/out/out). "
                    f"Operation index {idx} has from={from_value!r}."
                )
            if not _is_absolute_slot_endpoint(to_value):
                return (
                    "Invalid wiresheet payload: link 'to' must be an absolute slot endpoint under "
                    "an allowlisted root (not shorthand like out/inA/out/out). "
                    f"Operation index {idx} has to={to_value!r}."
                )

    return None
