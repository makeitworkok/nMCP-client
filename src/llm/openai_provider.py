"""OpenAI LLM provider (GPT-4o, GPT-4-turbo, …)."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from src.llm.base import BaseLLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """Wraps the OpenAI chat completions API with function-calling support."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )
        self._model = model
        self._messages: list[dict[str, Any]] = []

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
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        return LLMResponse(content=msg.content, tool_calls=tool_calls)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: Any) -> list[dict[str, Any]]:
        result = []
        for tool in tools:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                    },
                }
            )
        return result
