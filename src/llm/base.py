"""Abstract LLM provider interface and shared data-classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

try:
    from mcp.types import Tool
except ImportError:  # allow unit-testing without mcp installed
    Tool = Any  # type: ignore[assignment,misc]


@dataclass
class ToolCall:
    """Normalised representation of a single tool invocation."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalised response from any LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class BaseLLMProvider(ABC):
    """Common interface that every LLM provider must implement.

    Each provider maintains its own internal conversation history so that
    provider-specific message formats (OpenAI vs Anthropic) never leak into
    the agent loop.
    """

    # ------------------------------------------------------------------
    # Conversation management
    # ------------------------------------------------------------------

    @abstractmethod
    def reset_conversation(self, system_prompt: str | None = None) -> None:
        """Clear history and optionally set a system prompt."""

    @abstractmethod
    def add_user_message(self, content: str) -> None:
        """Append a user turn to the conversation."""

    @abstractmethod
    def add_tool_results_batch(
        self,
        results: list[tuple[str, str, str]],
    ) -> None:
        """Add one or more tool results.

        Parameters
        ----------
        results:
            List of ``(tool_call_id, tool_name, result_text)`` tuples.
            Providers that need batching (e.g. Anthropic) override this.
        """

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_response(self, tools: list[Tool]) -> LLMResponse:
        """Call the LLM with the current conversation and available tools."""
