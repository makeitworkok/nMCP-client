# Copyright (c) 2026 Chris Favre. All rights reserved.
"""nMCP client — wraps the official MCP Python SDK.

Supports Streamable HTTP transport (primary) and SSE transport (fallback).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from http.cookiejar import CookieJar
from contextlib import AsyncExitStack
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx
from mcp import ClientSession
from mcp.types import Implementation, Tool

from src.mcp_proxy import NiagaraSession

logger = logging.getLogger(__name__)


def _build_initialize_payload(agent_name: str) -> dict[str, Any]:
    """Return the MCP initialize payload used for connection preflight."""
    client_name = (agent_name or "nMCP-client").strip() or "nMCP-client"
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": "0.1.0"},
        },
    }


def build_headers(
    username: str = "",
    password: str = "",
    token: str = "",
) -> dict[str, str]:
    """Build HTTP auth headers from credentials."""
    headers: dict[str, str] = {}
    if token:
        headers["X-MCP-Token"] = token
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
        agent_name: str = "nMCP-client",
        username: str = "",
        password: str = "",
        token: str = "",
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
        await self.disconnect()
        hdrs = dict(headers or {})
        resolved_agent_name = (agent_name or "nMCP-client").strip() or "nMCP-client"
        self._apply_agent_headers(hdrs, resolved_agent_name)
        attempt_urls = self._candidate_endpoint_urls(url)
        last_exc: Exception | None = None

        for attempt_url in attempt_urls:
            exit_stack = AsyncExitStack()
            resolved_url = attempt_url
            try:
                try:
                    cookies, discovered_token = await self._build_session_auth(
                        resolved_url,
                        username,
                        password,
                        token,
                    )
                    self._apply_discovered_token_headers(hdrs, discovered_token)
                except RuntimeError as exc:
                    if self._should_retry_scram_over_https(resolved_url, exc):
                        resolved_url = self._to_https_url(resolved_url)
                        logger.warning(
                            "Authentication redirected on HTTP; retrying with HTTPS endpoint %s",
                            resolved_url,
                        )
                        cookies, discovered_token = await self._build_session_auth(
                            resolved_url,
                            username,
                            password,
                            token,
                        )
                        self._apply_discovered_token_headers(hdrs, discovered_token)
                    else:
                        raise

                if transport == "streamable_http":
                    await self._preflight_streamable_http(
                        resolved_url,
                        hdrs,
                        cookies,
                        resolved_agent_name,
                    )

                if transport == "sse":
                    from mcp.client.sse import sse_client

                    transport_cm = sse_client(resolved_url, headers=hdrs)
                else:
                    from mcp.client.streamable_http import streamable_http_client

                    http_client = httpx.AsyncClient(
                        headers=hdrs,
                        cookies=cookies,
                        follow_redirects=True,
                        verify=False,
                        timeout=httpx.Timeout(30.0, read=300.0),
                    )
                    transport_cm = streamable_http_client(
                        resolved_url,
                        http_client=http_client,
                    )

                streams = await exit_stack.enter_async_context(transport_cm)
                read_stream, write_stream = streams[0], streams[1]

                session = await exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        client_info=Implementation(
                            name=resolved_agent_name,
                            version="0.1.0",
                        ),
                    )
                )
                await session.initialize()
            except Exception as exc:
                last_exc = exc
                await exit_stack.aclose()
                logger.warning("Connection attempt failed for %s: %s", resolved_url, exc)
                continue

            self._exit_stack = exit_stack
            self._session = session
            self._url = resolved_url
            logger.info("Connected to MCP server at %s", resolved_url)
            return

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Connection failed before any endpoint attempt could be made.")

    async def _preflight_streamable_http(
        self,
        url: str,
        headers: dict[str, str],
        cookies: httpx.Cookies,
        agent_name: str,
    ) -> None:
        """Fail fast on auth/path errors before entering MCP transport internals."""
        payload = _build_initialize_payload(agent_name)
        async with httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            follow_redirects=True,
            verify=False,
            timeout=httpx.Timeout(30.0, read=30.0),
        ) as client:
            response = await client.post(url, json=payload)

        if response.status_code >= 400:
            snippet = response.text.strip()
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
            raise RuntimeError(
                f"MCP preflight failed with HTTP {response.status_code} for {url}: {snippet or '<empty response>'}"
            )

    async def _build_session_auth(
        self,
        url: str,
        username: str,
        password: str,
        token: str,
    ) -> tuple[httpx.Cookies, str]:
        """Create cookies and discovered backend token for Niagara-authenticated stations."""
        if not username:
            return httpx.Cookies(), ""

        base_url = self._base_url_for_endpoint(url)
        cookie_jar, discovered_token = await asyncio.to_thread(
            self._login_and_get_auth_data,
            base_url,
            username,
            password,
            token,
        )
        cookies = httpx.Cookies()
        for cookie in cookie_jar:
            cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        return cookies, discovered_token

    def _login_and_get_auth_data(
        self,
        base_url: str,
        username: str,
        password: str,
        token: str,
    ) -> tuple[CookieJar, str]:
        """Run Niagara authentication login and return session cookies + backend token."""
        session = NiagaraSession(base_url, username, password, token)
        session.login()
        discovered_token = getattr(session, "_backend_mcp_token", "").strip()
        return session._jar, discovered_token

    def _apply_discovered_token_headers(
        self,
        headers: dict[str, str],
        discovered_token: str,
    ) -> None:
        """Apply auto-discovered backend token if user did not provide one."""
        token = discovered_token.strip()
        if not token:
            return
        if headers.get("X-MCP-Token"):
            return

        headers["X-MCP-Token"] = token
        if not headers.get("Authorization"):
            headers["Authorization"] = f"Bearer {token}"

    def _apply_agent_headers(
        self,
        headers: dict[str, str],
        agent_name: str,
    ) -> None:
        """Apply MCP agent identity header expected by newer nMCP servers."""
        normalized = (agent_name or "nMCP-client").strip() or "nMCP-client"
        if not headers.get("X-MCP-Agent"):
            headers["X-MCP-Agent"] = normalized

    def _base_url_for_endpoint(self, url: str) -> str:
        """Return scheme://host[:port] from a full endpoint URL."""
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _normalize_endpoint_url(self, url: str) -> str:
        """Normalize user-provided endpoint (scheme + path defaults)."""
        cleaned = (url or "").strip()
        if not cleaned:
            return cleaned

        if "://" not in cleaned:
            cleaned = f"https://{cleaned}"

        parsed = urlsplit(cleaned)
        path = parsed.path or "/mcp"
        if not path.startswith("/"):
            path = f"/{path}"
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    def _candidate_endpoint_urls(self, url: str) -> list[str]:
        """Return ordered endpoint candidates, trying both /mcp and /nmcp when applicable."""
        normalized = self._normalize_endpoint_url(url)
        if not normalized:
            return []

        parsed = urlsplit(normalized)
        path = parsed.path.rstrip("/") or "/mcp"
        candidates = [normalized]

        alt_path = ""
        lower = path.lower()
        if lower.endswith("/mcp"):
            alt_path = f"{path[:-4]}/nmcp"
        elif lower.endswith("/nmcp"):
            alt_path = f"{path[:-5]}/mcp"

        if alt_path:
            alt_url = urlunsplit((parsed.scheme, parsed.netloc, alt_path, parsed.query, parsed.fragment))
            if alt_url not in candidates:
                candidates.append(alt_url)

        return candidates

    def _to_https_url(self, url: str) -> str:
        """Convert an HTTP endpoint URL to HTTPS while preserving host/path/query."""
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "http":
            return url
        return url.replace("http://", "https://", 1)

    def _should_retry_scram_over_https(self, url: str, exc: RuntimeError) -> bool:
        """Detect Niagara authentication redirect errors that should be retried over HTTPS."""
        if urlsplit(url).scheme.lower() != "http":
            return False

        message = str(exc)
        if "SCRAM POST" not in message or "j_security_check" not in message:
            return False

        return any(code in message for code in ("HTTP 301", "HTTP 302", "HTTP 303", "HTTP 307", "HTTP 308"))

    async def disconnect(self) -> None:
        """Close the MCP session cleanly."""
        await self._exit_stack.aclose()
        self._session = None
        self._tools = []
        logger.info("Disconnected from MCP server")

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    @property
    def endpoint_url(self) -> str:
        return self._url

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
        result = await asyncio.wait_for(
            self._session.call_tool(name, arguments),  # type: ignore[union-attr]
            timeout=30.0,
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_session(self) -> None:
        if self._session is None:
            raise RuntimeError("Not connected to an MCP server. Call connect() first.")
