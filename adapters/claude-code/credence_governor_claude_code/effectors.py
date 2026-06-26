"""effectors.py — a governor action -> a Claude Code PreToolUse decision.

The governor is an OVERLAY on Claude Code's native permission system, so it may only
ever ADD restriction, never remove it:

  proceed -> None        (emit nothing: defer to Claude Code's own permission rules)
  block   -> deny        (refuse regardless of native rules)
  ask     -> ask         (force a user prompt even if native rules would auto-allow)

We deliberately never emit permissionDecision "allow": that would bypass Claude
Code's native safety prompts, i.e. the governance layer weakening the host. A
returned None means "print nothing", which leaves the call to the normal flow.

Every ENFORCED decision (block/ask) also carries a top-level `systemMessage`, which
Claude Code shows to the USER. The permissionDecisionReason alone is easy to miss
(it reads mostly to the model), so the governor's action is never silent — see
test_effectors.test_block_carries_visible_system_message.

`shadow_output` is the observe-only counterpart (CREDENCE_GOVERNOR_SHADOW): it NEVER
enforces (no permissionDecision => the tool proceeds) but narrates what the governor
WOULD have done, so you can measure governance on real usage without being gated.
"""

from __future__ import annotations

from typing import Any

_DECISION = {"proceed": None, "block": "deny", "ask": "ask"}


def _reason(action: str, tool_name: str) -> str:
    tool = tool_name or "this tool"
    if action == "block":
        return f"credence-governor refused `{tool}`: low expected utility under the current belief (likely a loop or unsafe action)."
    return f"credence-governor wants confirmation before `{tool}` runs."


def _system_message(action: str, tool_name: str, *, shadow: bool) -> str | None:
    """The user-visible one-liner for an enforced (or shadowed) decision, or None
    when there is nothing to say (proceed / unknown action)."""
    tool = tool_name or "this tool"
    if action not in ("block", "ask"):
        return None
    if shadow:
        would = "block" if action == "block" else "ask before"
        return f"credence-governor [shadow]: would {would} `{tool}` — observing only, not enforcing."
    if action == "block":
        return f"credence-governor: blocked `{tool}` (low expected utility — likely a loop/unsafe action). Disable with /plugin."
    return f"credence-governor: asking for confirmation before `{tool}` runs."


def pretooluse_output(action: str, tool_name: str = "") -> dict[str, Any] | None:
    """The JSON to print on stdout for a PreToolUse hook, or None to print nothing
    (proceed / unknown action -> defer to Claude Code). Enforced decisions also carry
    a user-visible `systemMessage`."""
    decision = _DECISION.get(action)
    if decision is None:
        return None
    out: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": _reason(action, tool_name),
        }
    }
    msg = _system_message(action, tool_name, shadow=False)
    if msg:
        out["systemMessage"] = msg
    return out


def shadow_output(action: str, tool_name: str = "") -> dict[str, Any] | None:
    """Observe-only: NEVER enforce (no permissionDecision => the tool proceeds), but
    surface what the governor WOULD have done as a user-visible `systemMessage`. None
    when the decision was proceed (nothing to narrate)."""
    msg = _system_message(action, tool_name, shadow=True)
    return {"systemMessage": msg} if msg else None
