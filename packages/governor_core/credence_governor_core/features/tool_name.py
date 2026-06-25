"""tool_name.py — bucket the proposed tool's name into tool-name-space:
read | write | edit | bash | exec | process | apply_patch | grep | find | ls |
other. Lowercased before classification; anything not in KNOWN_TOOLS -> "other".
Port of extension/src/features/tool_name.ts.
"""

from __future__ import annotations

from ..schema import AgentToolEvent, Session

KNOWN_TOOLS: frozenset[str] = frozenset(
    {"read", "write", "edit", "bash", "exec", "process", "apply_patch", "grep", "find", "ls"}
)


def bucket(name: str) -> str:
    t = (name or "").lower()
    return t if t in KNOWN_TOOLS else "other"


def extract_tool_name(event: AgentToolEvent, _session: Session) -> str:
    return bucket(event.tool_name)
