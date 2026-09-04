"""Structured JSON logging.

Hard rule enforced by convention and by the ``text_fingerprint`` helper:
**prompt bodies never reach the logs.** Log a truncated content hash, a byte
length, and a token count. Nothing else about the text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from typing import Any

from app.config import settings

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # uvicorn's access log duplicates our request middleware and leaks query
    # strings into stdout. Our middleware logs what we actually want.
    logging.getLogger("uvicorn.access").disabled = True


def text_fingerprint(text: str) -> str:
    """A loggable, non-reversible stand-in for user text.

    Use this anywhere you are tempted to log the text itself.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
