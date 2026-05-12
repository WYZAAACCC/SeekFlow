"""EventBus — lightweight publish-subscribe for Agent lifecycle events."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[["Event"], None]


@dataclass
class Event:
    """An event emitted during Agent execution."""
    type: str  # "agent.start", "tool.end", "llm.stream_token", etc.
    data: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class EventBus:
    """Thread-safe publish-subscribe event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("tool.end", lambda e: print(e.data))
        bus.emit(Event(type="tool.end", data={"name": "search"}))
    """

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler. Use '*' for all events."""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

    def emit(self, event: Event) -> None:
        """Fire an event to all registered handlers."""
        event.timestamp = event.timestamp or time.time()
        handlers: list[EventHandler] = []

        with self._lock:
            if event.type in self._handlers:
                handlers.extend(self._handlers[event.type])
            if "*" in self._handlers:
                handlers.extend(self._handlers["*"])

        for h in handlers:
            try:
                h(event)
            except Exception:
                logger.debug(
                    f"Handler for '{event.type}' raised exception",
                    exc_info=True,
                )


# Global singleton
_global_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton."""
    global _global_bus
    with _bus_lock:
        if _global_bus is None:
            _global_bus = EventBus()
        return _global_bus


__all__ = ["Event", "EventBus", "get_event_bus"]
