"""repetition.py — bucket how many times the bucketed tool name appeared among
the last five tool_calls of the last twenty messages: rep-0|rep-1|rep-2|rep-3plus.
Port of extension/src/features/repetition.ts.
"""

from __future__ import annotations

from ..schema import AgentToolEvent, Session
from .tool_name import bucket

RECENT_MESSAGE_WINDOW = 20
RECENT_TOOL_CALL_WINDOW = 5


def extract_recent_repetition_count(event: AgentToolEvent, session: Session) -> str:
    target = bucket(event.tool_name)
    recent_messages = session.messages[-RECENT_MESSAGE_WINDOW:]
    recent_tool_calls = [m for m in recent_messages if m.role == "tool_call"][
        -RECENT_TOOL_CALL_WINDOW:
    ]
    matches = sum(1 for m in recent_tool_calls if bucket(m.tool_name or "") == target)
    if matches == 0:
        return "rep-0"
    if matches == 1:
        return "rep-1"
    if matches == 2:
        return "rep-2"
    return "rep-3plus"
