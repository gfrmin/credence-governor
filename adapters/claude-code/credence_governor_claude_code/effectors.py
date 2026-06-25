"""effectors.py — a governor action -> a Claude Code PreToolUse decision.

The governor is an OVERLAY on Claude Code's native permission system, so it may only
ever ADD restriction, never remove it:

  proceed -> None        (emit nothing: defer to Claude Code's own permission rules)
  block   -> deny        (refuse regardless of native rules)
  ask     -> ask         (force a user prompt even if native rules would auto-allow)

We deliberately never emit permissionDecision "allow": that would bypass Claude
Code's native safety prompts, i.e. the governance layer weakening the host. A
returned None means "print nothing", which leaves the call to the normal flow.
"""

from __future__ import annotations

from typing import Any

_DECISION = {"proceed": None, "block": "deny", "ask": "ask"}


def _reason(action: str, tool_name: str) -> str:
    tool = tool_name or "this tool"
    if action == "block":
        return f"credence-governor refused `{tool}`: low expected utility under the current belief (likely a loop or unsafe action)."
    return f"credence-governor wants confirmation before `{tool}` runs."


def pretooluse_output(action: str, tool_name: str = "") -> dict[str, Any] | None:
    """The JSON to print on stdout for a PreToolUse hook, or None to print nothing
    (proceed / unknown action -> defer to Claude Code)."""
    decision = _DECISION.get(action)
    if decision is None:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": _reason(action, tool_name),
        }
    }
