"""Anthropic LLM provider (Claude)."""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

from src.llm.base import BaseLLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    """Wraps the Anthropic Messages API with tool-use support."""

    def __init__(self, api_key: str, model: str = "claude-opus-4-5") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._messages: list[dict[str, Any]] = []
        self._system_prompt: str | None = None

    # ------------------------------------------------------------------
    # BaseLLMProvider
    # ------------------------------------------------------------------

    def reset_conversation(self, system_prompt: str | None = None) -> None:
        self._messages = []
        self._system_prompt = system_prompt

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_tool_results_batch(
        self,
        results: list[tuple[str, str, str]],
    ) -> None:
        """Anthropic requires all tool results for one assistant turn in a single user message."""
        content_blocks = [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result_text,
            }
            for tool_call_id, _tool_name, result_text in results
        ]
        self._messages.append({"role": "user", "content": content_blocks})

    async def get_response(self, tools: Any) -> LLMResponse:
        anthropic_tools = self._convert_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": self._messages,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        logger.debug(
            "Anthropic request: model=%s, messages=%d", self._model, len(self._messages)
        )
        response = await self._client.messages.create(**kwargs)

        # Persist assistant turn (raw content blocks)
        self._messages.append({"role": "assistant", "content": response.content})

        # Parse response
        text_content: str | None = None
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_content = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return LLMResponse(content=text_content, tool_calls=tool_calls)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
