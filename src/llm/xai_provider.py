# Copyright (c) 2026 Chris Favre. All rights reserved.
"""xAI (Grok) LLM provider — reuses the OpenAI-compatible API."""

from __future__ import annotations

from src.llm.openai_provider import OpenAIProvider

_XAI_BASE_URL = "https://api.x.ai/v1"
_XAI_DEFAULT_MODEL = "grok-3"


class XAIProvider(OpenAIProvider):
    """xAI Grok via its OpenAI-compatible REST endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = _XAI_DEFAULT_MODEL,
        base_url: str = _XAI_BASE_URL,
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
