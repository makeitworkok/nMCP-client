"""Ollama LLM provider — uses Ollama's OpenAI-compatible local endpoint."""

from __future__ import annotations

from src.llm.openai_provider import OpenAIProvider

_OLLAMA_BASE_URL = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_MODEL = "llama3.1"


class OllamaProvider(OpenAIProvider):
    """Local Ollama inference via its OpenAI-compatible REST endpoint.

    No API key is needed; ``"ollama"`` is used as a placeholder to satisfy
    the openai client library.
    """

    def __init__(
        self,
        model: str = _OLLAMA_DEFAULT_MODEL,
        base_url: str = _OLLAMA_BASE_URL,
    ) -> None:
        super().__init__(api_key="ollama", model=model, base_url=base_url)
