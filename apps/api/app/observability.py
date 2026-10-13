"""Minimal JSON logging and request correlation without vendor coupling."""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class MetricsRegistry:
    """Process-local, content-free counters and timing aggregates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._timings: defaultdict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, milliseconds: float) -> None:
        with self._lock:
            samples = self._timings[name]
            samples.append(round(milliseconds, 3))
            if len(samples) > 2_000:
                del samples[: len(samples) - 2_000]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timings = {
                name: {
                    "count": len(values),
                    "average": round(sum(values) / len(values), 3),
                    "max": max(values),
                }
                for name, values in self._timings.items()
                if values
            }
            return {"counters": dict(self._counters), "timings": timings}


metrics_registry = MetricsRegistry()


class JsonFormatter(logging.Formatter):
    """Render one structured JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        fields = getattr(record, "knemora_fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure root logging once for local stdout collection."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


class RequestMetricsMiddleware:
    """ASGI middleware that records route/status timings without request content."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status_code = 500

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", scope.get("path", "unknown"))
            method = str(scope.get("method", "UNKNOWN"))
            key = f"http.{method}.{route_path}.{status_code}"
            metrics_registry.increment(key)
            metrics_registry.observe(
                f"http.{method}.{route_path}.duration", (time.monotonic() - started) * 1_000
            )


__all__ = [
    "RequestMetricsMiddleware",
    "configure_logging",
    "metrics_registry",
    "request_id_context",
]
