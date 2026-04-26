"""Tests for V4c — structured logging setup.

Confirms ``JsonFormatter`` emits valid JSON with the expected
fields and merges ``extra={...}`` cleanly. ``setup_logging`` is
idempotent and routes ``cowork.<topic>`` records to stdout in
JSON shape.
"""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest
from cowork_core.logging_setup import JsonFormatter, setup_logging


@pytest.fixture(autouse=True)
def _restore_cowork_logger() -> None:
    """``setup_logging`` mutates the ``cowork`` logger (handlers +
    propagate). pytest's ``caplog`` fixture in OTHER test files
    relies on records propagating to the root logger; restoring the
    state after each test here keeps the cross-file isolation
    that pytest expects."""
    cowork = logging.getLogger("cowork")
    saved_handlers = list(cowork.handlers)
    saved_propagate = cowork.propagate
    saved_level = cowork.level
    yield
    for handler in list(cowork.handlers):
        cowork.removeHandler(handler)
    for handler in saved_handlers:
        cowork.addHandler(handler)
    cowork.propagate = saved_propagate
    cowork.setLevel(saved_level)


def test_json_formatter_emits_valid_json() -> None:
    rec = logging.LogRecord(
        name="cowork.settings",
        level=logging.INFO,
        pathname="/x.py",
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = JsonFormatter().format(rec)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "cowork.settings"
    assert parsed["msg"] == "hello world"
    assert "ts" in parsed


def test_json_formatter_merges_extra_dict_keys() -> None:
    rec = logging.LogRecord(
        name="cowork.audit",
        level=logging.INFO,
        pathname="/x.py",
        lineno=1,
        msg="event",
        args=(),
        exc_info=None,
    )
    rec.event = "tool_call"
    rec.tool_name = "fs_read"
    rec.user_id = "alice"
    parsed = json.loads(JsonFormatter().format(rec))
    assert parsed["event"] == "tool_call"
    assert parsed["tool_name"] == "fs_read"
    assert parsed["user_id"] == "alice"


def test_setup_logging_is_idempotent() -> None:
    """Calling setup_logging twice doesn't stack duplicate handlers
    (so log records aren't double-printed)."""
    setup_logging()
    handler_count_first = len(logging.getLogger("cowork").handlers)
    setup_logging()
    handler_count_second = len(logging.getLogger("cowork").handlers)
    assert handler_count_first == handler_count_second == 1


def test_setup_logging_writes_json_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_logging()
    logging.getLogger("cowork.settings").info(
        "test event",
        extra={"event": "demo", "n": 42},
    )
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["msg"] == "test event"
    assert parsed["event"] == "demo"
    assert parsed["n"] == 42
    assert parsed["logger"] == "cowork.settings"
