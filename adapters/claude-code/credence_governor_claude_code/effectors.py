"""effectors.py — a governor action -> a Claude Code PreToolUse decision.

The governor is an OVERLAY on Claude Code's native permission system: it may only ADD
restriction, never remove it. The brain emits proceed/block/ask; the body maps that to a
permissionDecision, refining `block` by the decision's category (from the daemon's /decide):

  proceed              -> None   (defer to Claude Code's own rules)
  block + safety       -> deny   (hard refuse — taint/exfil/destructive; no override)
  block + waste        -> ask    (OVERRIDABLE — flagged as likely a loop; you decide)
  block (no category)  -> deny   (conservative default when the daemon didn't classify)
  ask                  -> ask    (force a prompt even if native rules would auto-allow)

We never emit permissionDecision "allow" — that would weaken the host's own prompts. Every
enforced decision carries a top-level user-visible `systemMessage`; the waste case also says
how to make it stop (credence-governor-feedback). `shadow_output` narrates the same WITHOUT
enforcing (CREDENCE_GOVERNOR_SHADOW) — see test_effectors.
"""

from __future__ import annotations

from typing import Any

# A block is overridable only when the daemon classified it `waste`; otherwise (safety, or an
# older daemon that sent no category) it stays a hard deny — conservative when info is missing.
_PERMISSION = {"block-hard": "deny", "block-waste": "ask", "ask-confirm": "ask"}


def _kind(action: str, category: str | None) -> str | None:
    if action == "block":
        return "block-waste" if category == "waste" else "block-hard"
    if action == "ask":
        return "ask-confirm"
    return None  # proceed / unknown -> defer


def _reason(kind: str, tool: str) -> str:
    return {
        "block-hard": f"credence-governor refused `{tool}`: low expected utility under the current belief (likely unsafe).",
        "block-waste": f"credence-governor flags `{tool}` as low expected utility (likely a loop/waste). Approve to run anyway; `credence-governor-feedback reject` if it was right to stop.",
        "ask-confirm": f"credence-governor wants confirmation before `{tool}` runs.",
    }[kind]


def _system_message(kind: str, tool: str, *, shadow: bool) -> str:
    if shadow:
        would = {"block-hard": "block", "block-waste": "flag as waste", "ask-confirm": "ask before"}[kind]
        return f"credence-governor [shadow]: would {would} `{tool}` — observing only, not enforcing."
    return {
        "block-hard": f"credence-governor: blocked `{tool}` (low expected utility / unsafe). Disable with /plugin.",
        "block-waste": f"credence-governor: `{tool}` looks like waste/a loop — approve to run anyway. To stop asking, run: credence-governor-feedback approve.",
        "ask-confirm": f"credence-governor: asking for confirmation before `{tool}` runs.",
    }[kind]


def pretooluse_output(action: str, tool_name: str = "", category: str | None = None) -> dict[str, Any] | None:
    """The JSON to print for a PreToolUse hook, or None to defer (proceed / unknown). A
    waste-block is an OVERRIDABLE ask; a safety/unclassified block is a hard deny. Enforced
    decisions carry a user-visible systemMessage."""
    kind = _kind(action, category)
    if kind is None:
        return None
    tool = tool_name or "this tool"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": _PERMISSION[kind],
            "permissionDecisionReason": _reason(kind, tool),
        },
        "systemMessage": _system_message(kind, tool, shadow=False),
    }


def shadow_output(action: str, tool_name: str = "", category: str | None = None) -> dict[str, Any] | None:
    """Observe-only: NEVER enforce (no permissionDecision => the tool proceeds), but narrate
    what the governor WOULD have done. None when the decision was proceed."""
    kind = _kind(action, category)
    if kind is None:
        return None
    return {"systemMessage": _system_message(kind, tool_name or "this tool", shadow=True)}
