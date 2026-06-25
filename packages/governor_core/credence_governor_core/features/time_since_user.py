"""time_since_user.py — classify elapsed time since the last user message into
time-since-user-space: lt-30s | lt-2m | lt-10m | gt-10m. No user message, or one
without a parseable timestamp, buckets to gt-10m (treat the user as away).
Port of extension/src/features/time_since_user.ts.
"""

from __future__ import annotations

import time
from datetime import datetime

from ..schema import AgentToolEvent, Session


def _parse_ms(timestamp: str) -> float | None:
    """ISO-8601 -> epoch milliseconds, or None if unparseable (mirrors Date.parse)."""
    try:
        ts = timestamp.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp() * 1000.0
    except (ValueError, AttributeError):
        return None


def extract_time_since_last_user_message(
    _event: AgentToolEvent,
    session: Session,
    now_ms: float | None = None,  # injectable for deterministic tests
) -> str:
    now = now_ms if now_ms is not None else time.time() * 1000.0
    for m in reversed(session.messages):
        if m.role != "user":
            continue
        if not m.timestamp:
            return "gt-10m"
        t = _parse_ms(m.timestamp)
        if t is None:
            return "gt-10m"
        elapsed_sec = (now - t) / 1000.0
        if elapsed_sec < 30:
            return "lt-30s"
        if elapsed_sec < 120:
            return "lt-2m"
        if elapsed_sec < 600:
            return "lt-10m"
        return "gt-10m"
    return "gt-10m"
