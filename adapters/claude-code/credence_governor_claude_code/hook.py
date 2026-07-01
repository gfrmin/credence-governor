"""hook.py — the Claude Code subprocess-hook entry point.

Registered as a `PreToolUse` hook (see install.py / settings.example.json). On each
proposed tool call Claude Code pipes a JSON event on stdin; we translate it to the
neutral wire shape, ask the governor daemon for a decision, and print a PreToolUse
permission decision on stdout.

v1 gates PreToolUse only. PostToolUse / UserPromptSubmit are intentionally NOT wired:
neither carries a clean approval label, and recording "the call completed" as belief
evidence would be a second learning path (Invariant 1) — wrong, not just weak. Online
ask-learning on Claude Code is an open design question (transcript-inference), so v1
is observation-only: the warm-trained brain governs, the daemon logs every decision.

Fail-open is absolute: any malformed input, daemon-down, timeout, or non-PreToolUse
event prints nothing and exits 0, leaving the call to Claude Code's normal flow. The
governor can add friction (deny / ask) but never removes the host's own safety.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import client, effectors, transcript


def _debug(msg: str) -> None:
    if os.environ.get("CREDENCE_GOVERNOR_DEBUG"):
        sys.stderr.write(f"credence-governor: {msg}\n")


def _shadow() -> bool:
    """Observe-only mode: the daemon still decides + logs, but the body never enforces
    (parity with the OpenClaw adapter's shadowMode). Safe way to run the governor while
    its beliefs are still being calibrated."""
    return os.environ.get("CREDENCE_GOVERNOR_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def _deny_categories() -> frozenset[str]:
    """Advisory categories the operator opted into HARD (non-overridable) enforcement,
    from CREDENCE_GOVERNOR_DENY_CATEGORIES (comma-separated, e.g. `safety` or `safety,waste`).
    Default empty => every gated decision is an overridable ask (the human is the authority)."""
    raw = os.environ.get("CREDENCE_GOVERNOR_DENY_CATEGORIES", "")
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    return json.loads(raw) if raw and raw.strip() else {}


def handle(hook_input: dict[str, Any]) -> dict[str, Any] | None:
    """Pure core: a PreToolUse hook payload -> the stdout JSON (or None to defer).
    Raises on daemon failure so `main` can fail open around it."""
    if (hook_input.get("hook_event_name") or "") != "PreToolUse":
        return None  # v1 gates only PreToolUse
    payload = transcript.session_from_hook(hook_input)
    profile = os.environ.get("CREDENCE_GOVERNOR_PROFILE")
    if profile:
        payload["profile"] = profile
    result = client.decide(payload)
    action = str(result.get("action") or "proceed")
    category = result.get("category")  # safety|waste — ADVISORY; overridability is policy
    rationale = result.get("rationale")  # the structural "why" — a legible, specific reason
    deny = _deny_categories()          # default empty => every gated decision is overridable
    _debug(f"{payload['tool_name']} -> {action}/{category} deny={set(deny) or '∅'} ({result.get('features')})")
    if _shadow():
        return effectors.shadow_output(action, payload["tool_name"], category, deny, rationale)
    return effectors.pretooluse_output(action, payload["tool_name"], category, deny, rationale)


def main() -> int:
    try:
        hook_input = _read_stdin()
    except (ValueError, OSError) as err:
        _debug(f"unreadable stdin (failing open): {err}")
        return 0
    try:
        out = handle(hook_input)
    except Exception as err:  # fail-open: daemon down, timeout, anything
        _debug(
            "decision error — failing open (tool proceeds UNGOVERNED). Is the daemon up "
            f"on :{client.DEFAULT_PORT}? Start it: {client.DAEMON_CMD} — err: {err}"
        )
        return 0
    if out is not None:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
