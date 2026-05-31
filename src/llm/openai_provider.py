# Copyright (c) 2026 Chris Favre. All rights reserved.
"""OpenAI LLM provider (GPT-4o, GPT-4-turbo, …)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from src.llm.base import BaseLLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

_OPENAI_TOOL_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_MAX_OPENAI_TOOL_NAME_LENGTH = 64


class OpenAIProvider(BaseLLMProvider):
    """Wraps the OpenAI chat completions API with function-calling support."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            default_headers=default_headers,
        )
        self._model = model
        self._messages: list[dict[str, Any]] = []
        self._tool_name_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # BaseLLMProvider
    # ------------------------------------------------------------------

    def reset_conversation(self, system_prompt: str | None = None) -> None:
        self._messages = []
        if system_prompt:
            self._messages.append({"role": "system", "content": system_prompt})

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_tool_results_batch(
        self,
        results: list[tuple[str, str, str]],
    ) -> None:
        for tool_call_id, _tool_name, result_text in results:
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_text,
                }
            )

    async def get_response(self, tools: Any) -> LLMResponse:
        oai_tools = self._convert_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools
            kwargs["tool_choice"] = "auto"

        logger.debug("OpenAI request: model=%s, messages=%d", self._model, len(self._messages))
        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        # Persist assistant turn in history
        assistant_entry: dict[str, Any] = {"role": "assistant"}
        if msg.content:
            assistant_entry["content"] = msg.content
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        self._messages.append(assistant_entry)

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_name = self._tool_name_map.get(tc.function.name, tc.function.name)
                tool_calls.append(
                    ToolCall(id=tc.id, name=tool_name, arguments=args)
                )

        return LLMResponse(content=msg.content, tool_calls=tool_calls)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _convert_tools(self, tools: Any) -> list[dict[str, Any]]:
        self._tool_name_map = {}
        result = []
        for tool in tools:
            openai_name = self._to_openai_tool_name(tool.name)
            self._tool_name_map[openai_name] = tool.name
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": openai_name,
                        "description": tool.description or "",
                        "parameters": self._normalize_schema(
                            tool.inputSchema or {"type": "object", "properties": {}}
                        ),
                    },
                }
            )
        return result

    def _normalize_schema(self, schema: Any) -> Any:
        """Convert MCP JSON Schema into an OpenAI-compatible function schema."""
        if not isinstance(schema, dict):
            return schema

        normalized = {key: self._normalize_schema(value) for key, value in schema.items()}
        schema_type = normalized.get("type")

        if schema_type == "object":
            properties = normalized.get("properties")
            if not isinstance(properties, dict):
                normalized["properties"] = {}
            if "required" in normalized and not isinstance(normalized["required"], list):
                normalized.pop("required", None)

        if schema_type == "array":
            items = normalized.get("items")
            if items is None:
                normalized["items"] = {}

        return normalized

    def _to_openai_tool_name(self, tool_name: str) -> str:
        """Convert an MCP tool name into an OpenAI-compatible function name."""
        sanitized = _OPENAI_TOOL_NAME_PATTERN.sub("_", tool_name).strip("_")
        if not sanitized:
            sanitized = "tool"

        if len(sanitized) <= _MAX_OPENAI_TOOL_NAME_LENGTH and sanitized not in self._tool_name_map:
            return sanitized

        digest = hashlib.sha1(tool_name.encode("utf-8")).hexdigest()[:8]
        prefix_length = _MAX_OPENAI_TOOL_NAME_LENGTH - len(digest) - 1
        prefix = sanitized[:prefix_length].rstrip("_") or "tool"
        candidate = f"{prefix}_{digest}"

        if candidate in self._tool_name_map and self._tool_name_map[candidate] != tool_name:
            raise ValueError(f"Unable to generate unique OpenAI tool name for {tool_name!r}")

        return candidate
