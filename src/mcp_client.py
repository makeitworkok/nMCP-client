"""Niagara MCP client — wraps the official MCP Python SDK.

Supports Streamable HTTP transport (primary) and SSE transport (fallback).
"""

from __future__ import annotations

import base64
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.types import Tool

logger = logging.getLogger(__name__)


def build_headers(
    username: str = "",
    password: str = "",
    token: str = "",
) -> dict[str, str]:
    """Build HTTP auth headers from credentials."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif username:
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    return headers


class NiagaraMCPClient:
    """Async MCP client that maintains a long-lived server session."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()
        self._tools: list[Tool] = []
        self._url: str = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        transport: str = "streamable_http",
    ) -> None:
        """Open a connection to the MCP server.

        Parameters
        ----------
        url:
            Full MCP endpoint URL, e.g. ``http://host:8000/mcp``.
        headers:
            Optional HTTP headers (e.g. Authorization).
        transport:
            ``"streamable_http"`` (default) or ``"sse"``.
        """
        await self._exit_stack.aclose()
        self._exit_stack = AsyncExitStack()
        self._url = url
        hdrs = headers or {}

        if transport == "sse":
            from mcp.client.sse import sse_client

            transport_cm = sse_client(url, headers=hdrs)
        else:
            from mcp.client.streamable_http import streamablehttp_client

            transport_cm = streamablehttp_client(url, headers=hdrs)

        streams = await self._exit_stack.enter_async_context(transport_cm)
        read_stream, write_stream = streams[0], streams[1]

        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        logger.info("Connected to MCP server at %s", url)

    async def disconnect(self) -> None:
        """Close the MCP session cleanly."""
        await self._exit_stack.aclose()
        self._session = None
        self._tools = []
        logger.info("Disconnected from MCP server")

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[Tool]:
        """Fetch available tools from the server."""
        self._require_session()
        response = await self._session.list_tools()  # type: ignore[union-attr]
        self._tools = response.tools
        logger.info("Discovered %d tools", len(self._tools))
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool on the MCP server."""
        self._require_session()
        logger.debug("Calling tool %s with %s", name, arguments)
        result = await self._session.call_tool(name, arguments)  # type: ignore[union-attr]
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_session(self) -> None:
        if self._session is None:
            raise RuntimeError("Not connected to an MCP server. Call connect() first.")
