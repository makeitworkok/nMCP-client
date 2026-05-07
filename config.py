"""Application configuration — loaded from JSON and optionally seeded from .env."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()  # populate os.environ from .env (if present)

CONFIG_PATH = Path.home() / ".nmcp_client" / "config.json"


class ConnectionConfig(BaseModel):
    mcp_url: str = Field(
        default_factory=lambda: os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
    )
    station_name: str = Field(
        default_factory=lambda: os.getenv("NIAGARA_STATION_NAME", "")
    )
    username: str = Field(
        default_factory=lambda: os.getenv("NIAGARA_USERNAME", "")
    )
    password: str = Field(
        default_factory=lambda: os.getenv("NIAGARA_PASSWORD", "")
    )
    token: str = Field(
        default_factory=lambda: os.getenv("NIAGARA_TOKEN", "")
    )


class LLMConfig(BaseModel):
    provider: str = "openai"  # openai | anthropic | xai | ollama
    model: str = "gpt-4o"
    api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    base_url: str = ""  # optional override (e.g. local proxy)


class AppConfig(BaseModel):
    connection: ConnectionConfig = Field(default_factory=ConnectionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_config() -> AppConfig:
    """Load config from disk, falling back to defaults."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                data = json.load(f)
            return AppConfig(**data)
        except Exception:
            pass  # corrupt config — start fresh
    return AppConfig()


def save_config(config: AppConfig) -> None:
    """Persist config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(config.model_dump(), f, indent=2)
