"""parent_tool.py — classify the most recent prior tool_call into
parent-tool-name-space: the tool buckets plus "none" (no preceding tool_call).
The proposed call is NOT yet in session.messages, so we read the tail.
Port of extension/src/features/parent_tool.ts.
"""

from __future__ import annotations

from ..schema import AgentToolEvent, Session
from .tool_name import KNOWN_TOOLS


def extract_parent_tool_call_name(_event: AgentToolEvent, session: Session) -> str:
    for m in reversed(session.messages):
        if m.role != "tool_call":
            continue
        t = (m.tool_name or "").lower()
        return t if t in KNOWN_TOOLS else "other"
    return "none"
