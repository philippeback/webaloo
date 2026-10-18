from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .storage import Storage

logger = logging.getLogger("webaloo.watcher")


class FileWatcherBroadcaster:
    """
    REQ-SYNC-001 & REQ-SYNC-002:
    Monitors the root webmixes directory for external changes, updates the in-memory
    search cache, and broadcasts reload notifications to connected SSE clients.
    """

    def __init__(self, storage: Storage):
        self.storage = storage
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(q)

    async def broadcast(self, event_type: str = "reload", payload: dict[str, Any] | None = None) -> None:
        self.storage.invalidate_cache()
        self.storage.rebuild_search_index()
        msg = {
            "event": event_type,
            "data": payload or {"timestamp": time.time()},
        }
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except Exception:
                self.subscribers.discard(q)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch_loop(self) -> None:
        try:
            from watchfiles import awatch

            async for changes in awatch(self.storage.root_dir, debounce=300, step=100):
                if not self._running:
                    break
                # Ignore echoes from our own recent internal writes within 450ms
                if time.monotonic() - self.storage._last_internal_write < 0.45:
                    continue
                changed_files = [str(Path(p).name) for _, p in changes]
                logger.info("External filesystem change detected: %s", changed_files)
                await self.broadcast("reload", {"files": changed_files, "timestamp": time.time()})
        except ImportError:
            logger.info("watchfiles not installed; using asyncio snapshot polling watcher.")
            await self._polling_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Watcher error (%s), falling back to polling loop.", exc)
            await self._polling_loop()

    def _take_snapshot(self) -> dict[str, float]:
        snap: dict[str, float] = {}
        if not self.storage.root_dir.exists():
            return snap
        for p in self.storage.root_dir.rglob("*"):
            try:
                if p.is_file() or p.is_dir():
                    snap[str(p)] = p.stat().st_mtime
            except OSError:
                continue
        return snap

    async def _polling_loop(self) -> None:
        last_snap = self._take_snapshot()
        while self._running:
            await asyncio.sleep(1.0)
            current_snap = self._take_snapshot()
            if current_snap != last_snap:
                last_snap = current_snap
                if time.monotonic() - self.storage._last_internal_write < 0.6:
                    continue
                await self.broadcast("reload", {"timestamp": time.time()})
