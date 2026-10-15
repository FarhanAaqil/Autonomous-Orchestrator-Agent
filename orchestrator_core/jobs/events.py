"""
orchestrator_core/jobs/events.py

In-memory event hub for SSE streaming of real-time job state transitions and step traces.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class JobEventHub:
    """Manages active SSE subscriber queues for job events with Last-Event-ID replay."""

    def __init__(self, history_size: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._counter: int = 0
        self._history: list[tuple[int, str]] = []  # (event_id, formatted_sse_msg)
        self._history_size = history_size

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event with monotonic ID to history and all connected subscriber queues."""
        self._counter += 1
        event_id = self._counter
        payload = {
            "id": event_id,
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        msg = f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(payload)}\n\n"

        # Retain recent events for Last-Event-ID reconnection replay
        self._history.append((event_id, msg))
        if len(self._history) > self._history_size:
            self._history.pop(0)

        dead_queues = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead_queues.append(q)

        for q in dead_queues:
            self._subscribers.discard(q)

    async def subscribe(self, last_event_id: Optional[str] = None) -> AsyncGenerator[str, None]:
        """
        Async generator yielding SSE formatted strings to a client.
        Replays buffered events if last_event_id is provided.
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

        # Replay missed events if client reconnected with Last-Event-ID
        if last_event_id is not None:
            try:
                last_id_int = int(last_event_id)
                for eid, emsg in self._history:
                    if eid > last_id_int:
                        queue.put_nowait(emsg)
            except (ValueError, asyncio.QueueFull):
                pass

        self._subscribers.add(queue)
        try:
            # If no replayed events are ready, immediately yield an initial comment so Starlette/ASGI
            # flushes HTTP 200 headers to the browser EventSource without waiting for a new event.
            if queue.empty():
                yield ": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat ping preventing proxy/browser dropped connection
                    yield ": ping\n\n"
        finally:
            self._subscribers.discard(queue)


# Global singleton event hub instance
event_hub = JobEventHub()
