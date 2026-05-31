# Copyright (c) 2026 Chris Favre. All rights reserved.
"""OpenRouter LLM provider — reuses OpenAI-compatible chat completions."""

from __future__ import annotations

from src.llm.openai_provider import OpenAIProvider

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter via its OpenAI-compatible REST endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = _OPENROUTER_DEFAULT_MODEL,
        base_url: str = _OPENROUTER_BASE_URL,
    ) -> None:
        # OpenRouter recommends including these headers for request attribution.
        default_headers = {
            "HTTP-Referer": "https://github.com/makeitworkok/nMCP-client",
            "X-Title": "nMCP Client",
        }
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            default_headers=default_headers,
        )
