"""effectors.py — a governor action -> a Claude Code PreToolUse decision.

The governor is an OVERLAY on Claude Code's native permission system: it may only ADD
restriction, never remove it. The brain emits proceed/block/ask; the body maps that to a
permissionDecision.

OVERRIDABILITY IS A POLICY, NOT A FIXED RULE. The default is that EVERY gated decision is
overridable — the governor SURFACES risk to the human operator, who is the final authority
(this is the fail-open posture, and it is consistent with finite harm-cost EU: a human
"I actually want this" is admissible evidence, so nothing is categorically un-overridable):

  proceed                          -> None   (defer to Claude Code's own rules)
  ask                              -> ask    (overridable confirmation)
  block (any category, default)    -> ask    (overridable — the human decides)

An operator who wants HARD enforcement for some advisory categories opts in via
`deny_categories` (CREDENCE_GOVERNOR_DENY_CATEGORIES, e.g. "safety"): a block whose
advisory `category` (from the daemon's /decide — `safety` taint/exfil/destructive,
`waste` loop/low-value) is in that set becomes a non-overridable `deny`. Default is the
empty set => all overridable.

The `category` is ADVISORY either way: it always shapes the human-facing message ("looks
unsafe" vs "looks like a loop"); it only gates overridability when the operator opted that
category into `deny_categories`.

We never emit permissionDecision "allow" — that would weaken the host's own prompts. Every
enforced decision carries a top-level user-visible `systemMessage`. `shadow_output` narrates
the same WITHOUT enforcing (CREDENCE_GOVERNOR_SHADOW) — see test_effectors.
"""

from __future__ import annotations

from typing import Any

# advisory descriptor per category — what the governor THINKS, independent of enforcement.
_ADVICE = {
    "safety": "likely unsafe (taint/exfil/destructive)",
    "waste": "likely a loop/waste",
}
_ADVICE_DEFAULT = "low expected utility"


def _advice(category: str | None) -> str:
    return _ADVICE.get(category or "", _ADVICE_DEFAULT)


def _decision(action: str, category: str | None, deny_categories: frozenset[str]) -> str | None:
    """The host permissionDecision: `deny` (non-overridable) only for a block whose advisory
    category the operator opted into hard enforcement; every other gated decision is an
    overridable `ask`. Empty deny_categories (the default) => all gated decisions overridable."""
    if action == "block":
        return "deny" if category in deny_categories else "ask"
    if action == "ask":
        return "ask"
    return None  # proceed / unknown -> defer


def _reason(decision: str, category: str | None, tool: str, rationale: str | None = None) -> str:
    # Prefer the daemon's SPECIFIC structural rationale ("reads a credential store and sends it
    # to an unknown external host") over the generic per-category advice — a legible reason is
    # what makes an override a trustworthy calibration signal.
    advice = rationale or _advice(category)
    if decision == "deny":
        return f"credence-governor refused `{tool}`: {advice}."
    return (
        f"credence-governor flags `{tool}` as {advice}. Approve to run anyway; "
        f"`credence-governor-feedback reject` if it was right to stop."
    )


def _system_message(
    decision: str, category: str | None, tool: str, *, shadow: bool, rationale: str | None = None
) -> str:
    advice = rationale or _advice(category)
    if shadow:
        verb = "deny" if decision == "deny" else "ask before"
        return f"credence-governor [shadow]: would {verb} `{tool}` ({advice}) — observing only, not enforcing."
    if decision == "deny":
        return f"credence-governor: blocked `{tool}` ({advice}). Disable with /plugin."
    return (
        f"credence-governor: `{tool}` looks {advice} — approve to run anyway. "
        "To stop asking, run: credence-governor-feedback approve."
    )


def pretooluse_output(
    action: str,
    tool_name: str = "",
    category: str | None = None,
    deny_categories: frozenset[str] = frozenset(),
    rationale: str | None = None,
) -> dict[str, Any] | None:
    """The JSON to print for a PreToolUse hook, or None to defer (proceed / unknown). Every
    gated decision is an overridable `ask` unless the operator opted its advisory category
    into `deny_categories` (then a non-overridable `deny`). Enforced decisions carry a
    user-visible systemMessage. `rationale` (the daemon's structural "why") is preferred over
    the generic per-category advice when present."""
    decision = _decision(action, category, deny_categories)
    if decision is None:
        return None
    tool = tool_name or "this tool"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": _reason(decision, category, tool, rationale),
        },
        "systemMessage": _system_message(decision, category, tool, shadow=False, rationale=rationale),
    }


def shadow_output(
    action: str,
    tool_name: str = "",
    category: str | None = None,
    deny_categories: frozenset[str] = frozenset(),
    rationale: str | None = None,
) -> dict[str, Any] | None:
    """Observe-only: NEVER enforce (no permissionDecision => the tool proceeds), but narrate
    what the governor WOULD have done under the active policy. None when the decision was
    proceed."""
    decision = _decision(action, category, deny_categories)
    if decision is None:
        return None
    return {
        "systemMessage": _system_message(
            decision, category, tool_name or "this tool", shadow=True, rationale=rationale
        )
    }
