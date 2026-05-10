# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Runs an asyncio event loop in a background QThread.

Usage
-----
runner = AsyncRunner()
runner.start()

future = runner.submit(some_coroutine())   # concurrent.futures.Future
future.add_done_callback(...)

runner.stop()
runner.wait()
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine

from PySide6.QtCore import QThread


class AsyncRunner(QThread):
    """A QThread that owns and runs a dedicated asyncio event loop."""

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    # QThread API
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def stop(self) -> None:
        """Request the event loop to stop."""
        loop = self._get_loop()
        loop.call_soon_threadsafe(loop.stop)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        self._ready.wait()
        assert self._loop is not None
        return self._loop

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the running asyncio event loop (blocks until ready)."""
        return self._get_loop()

    def submit(self, coro: Coroutine[Any, Any, Any]):
        """Schedule *coro* on the asyncio loop; return a concurrent Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._get_loop())
