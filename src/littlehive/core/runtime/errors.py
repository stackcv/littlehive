from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ErrorInfo:
    category: str
    component: str
    error_type: str
    message_signature: str
    retryable: bool
    http_status: int | None = None


def _normalize_message(message: str, max_len: int = 180) -> str:
    msg = message.lower()
    msg = re.sub(r"\s+", " ", msg)
    msg = re.sub(r"\d+", "#", msg)
    return msg.strip()[:max_len]


def _compact_message(message: str, max_len: int = 220) -> str:
    msg = message.lower()
    msg = re.sub(r"\s+", " ", msg)
    return msg.strip()[:max_len]


def classify_error(exc: Exception, *, category: str, component: str) -> ErrorInfo:
    name = exc.__class__.__name__.lower()
    msg = str(exc)
    normalized = _normalize_message(msg)

    retryable = True
    lowered = f"{name} {normalized}"
    if any(k in lowered for k in ["auth", "unauthorized", "forbidden", "invalidrequest", "badrequest", "permission"]):
        retryable = False
    if any(k in lowered for k in ["timeout", "temporar", "connection", "reset", "unavailable", "5##"]):
        retryable = True

    status = None
    m = re.search(r"\b(4\d\d|5\d\d)\b", lowered)
    if m:
        status = int(m.group(1))
        if 400 <= status < 500 and status not in {408, 429}:
            retryable = False

    return ErrorInfo(
        category=category,
        component=component,
        error_type=exc.__class__.__name__,
        message_signature=normalized,
        retryable=retryable,
        http_status=status,
    )


def compact_error_summary(exc: Exception, max_len: int = 220) -> str:
    return f"{exc.__class__.__name__}: {_compact_message(str(exc), max_len=max_len)}"
