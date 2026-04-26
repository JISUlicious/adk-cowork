"""Structured logging setup (Slice V4c).

Replaces ad-hoc ``print(..., flush=True)`` lines (``[settings]``,
``[storage]``, ``[config]``) with a Python ``logging`` configuration
that emits one JSON object per record on stdout.

Why JSON: log aggregators (Loki, Vector, CloudWatch Logs Insights,
plain ``jq``) parse one-line JSON natively. The previous ``[topic]
prose`` format read OK by eye but had no schema — operators couldn't
filter by topic + key + level without ad-hoc regex.

Why custom formatter (no extra dep): ``python-json-logger`` would
work but adds a transitive dependency for what's about a dozen
lines of code. Stdlib ``logging.Formatter`` plus a small ``format``
override does the job.

Why stdout: matches the existing print-to-stdout convention so log
tailers (``tail -f``, the Tauri sidecar's stdout pipe, the
``cowork-cli`` chat handshake parser) keep seeing all log records on
the same channel they always did. The COWORK_READY handshake line
itself stays as a plain print — it's a single text line the launcher
parses by prefix, not a structured log record.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record. Top-level keys: ``ts``,
    ``level``, ``logger``, ``msg``. Any extra ``extra={...}`` from
    the call site is merged in flat (non-conflicting keys only)."""

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        from datetime import UTC, datetime

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge any extras the call site supplied via logger.info("...", extra={...}).
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value, default=str)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent — installs a single JSON-formatter handler on the
    ``cowork`` logger hierarchy. Safe to call multiple times; later
    calls replace the handlers rather than stacking duplicates.

    Backend ``__main__.py`` calls this at startup. Tests skip the
    call (the default Python logging config + pytest's ``caplog``
    fixture is enough)."""
    root = logging.getLogger("cowork")
    # Drop any prior handlers so calling setup_logging twice doesn't
    # duplicate every record.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    # Don't propagate to the root logger — avoids double-printing
    # when both root and "cowork" have handlers configured.
    root.propagate = False
