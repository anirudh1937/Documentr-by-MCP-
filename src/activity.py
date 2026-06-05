"""
Shared activity tracker for the backend dashboard.

Thread-safe event queue that the FastAPI middleware writes to
and the admin GUI reads from.
"""

from __future__ import annotations

import logging
import os
import platform
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("doc-editor.activity")


@dataclass
class ActivityEvent:
    """A single backend activity event."""
    timestamp: datetime
    method: str           # GET, POST, PUT, DELETE, WS, MCP, SYSTEM
    path: str
    status: int = 0
    duration_ms: float = 0
    detail: str = ""
    client: str = ""
    intent: str = ""


class ActivityTracker:
    """Thread-safe activity tracker shared between server and GUI."""

    def __init__(self):
        self.events: queue.Queue[ActivityEvent] = queue.Queue(maxsize=500)
        self._lock = threading.Lock()
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._total_ws_messages: int = 0
        self.start_time: datetime = datetime.now(timezone.utc)
        self._latencies: list[float] = []

    # ── Thread-safe property accessors ────────────────────────────

    @property
    def total_requests(self) -> int:
        with self._lock:
            return self._total_requests

    @property
    def total_errors(self) -> int:
        with self._lock:
            return self._total_errors

    @property
    def total_ws_messages(self) -> int:
        with self._lock:
            return self._total_ws_messages

    # ── Core logging ──────────────────────────────────────────────

    def log(
        self,
        method: str,
        path: str,
        status: int = 200,
        duration_ms: float = 0,
        detail: str = "",
        client: str = "",
        intent: str = "",
    ):
        """Log an activity event (called from FastAPI middleware)."""
        event = ActivityEvent(
            timestamp=datetime.now(timezone.utc),
            method=method.upper(),
            path=path,
            status=status,
            duration_ms=round(duration_ms, 1),
            detail=detail,
            client=client,
            intent=intent,
        )

        # Update counters atomically
        with self._lock:
            if method.upper() not in ("WS", "SYSTEM", "MCP"):
                self._total_requests += 1
                if status >= 400:
                    self._total_errors += 1
                self._latencies.append(duration_ms)
                if len(self._latencies) > 50:
                    self._latencies.pop(0)
            elif method.upper() == "WS":
                self._total_ws_messages += 1

        # Put in queue (non-blocking)
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
                self.events.put_nowait(event)
            except queue.Empty:
                pass

    @property
    def avg_latency_ms(self) -> float:
        with self._lock:
            if not self._latencies:
                return 0
            return sum(self._latencies) / len(self._latencies)

    @property
    def error_rate(self) -> float:
        with self._lock:
            if self._total_requests == 0:
                return 0
            return (self._total_errors / self._total_requests) * 100

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self.start_time).total_seconds())

    @property
    def uptime_str(self) -> str:
        s = self.uptime_seconds
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h}h {m}m {sec}s"
        elif m > 0:
            return f"{m}m {sec}s"
        return f"{sec}s"

    def get_server_info(self) -> dict:
        """Return server metadata."""
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem_mb = proc.memory_info().rss / (1024 * 1024)
            memory = f"{mem_mb:.1f} MB"
        except ImportError:
            memory = "N/A (install psutil)"
        except Exception as e:
            logger.debug(f"Failed to get memory info: {e}")
            memory = "N/A"

        return {
            "server_name": "DocumentEditor",
            "transport": "stdio (MCP) + HTTP (Web)",
            "api_server": "FastAPI + Uvicorn",
            "runtime": f"Python {sys.version.split()[0]}",
            "platform": platform.system() + " " + platform.release(),
            "storage": "JSON / disk",
            "host": "localhost",
            "pid": os.getpid(),
            "memory": memory,
            "port": 8765,
        }

    def drain_events(self) -> list[ActivityEvent]:
        """Drain all pending events from the queue (called from GUI)."""
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def reset(self):
        """Reset all counters and clear the event queue. Useful for clean restarts."""
        with self._lock:
            self._total_requests = 0
            self._total_errors = 0
            self._total_ws_messages = 0
            self._latencies.clear()
            self.start_time = datetime.now(timezone.utc)

        # Drain the queue
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break


# Global singleton
tracker = ActivityTracker()
