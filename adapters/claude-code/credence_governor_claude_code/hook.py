"""hook.py — the Claude Code subprocess-hook entry point.

Registered as `PreToolUse` + `PostToolUse` hooks (see install.py / settings.example.json).

PreToolUse: Claude Code pipes a proposed tool call as JSON on stdin; we translate it to the
neutral wire shape, ask the governor daemon for a decision, and print a PreToolUse permission
decision on stdout. We also stash the decide-time event_id keyed by the call's identity so the
matching PostToolUse can correlate to it (Claude Code fires the two as separate subprocesses).

PostToolUse: we recover that event_id, measure the call's latency, read the completion status
from the tool_response, and POST a MEASURED outcome to the daemon's /result — telemetry only,
never a belief update (recording "the call completed" as approval evidence would be a second,
wrong learning path, Invariant 1). The outcome is a measured observable, not a good/bad label.

Fail-open is absolute: any malformed input, daemon-down, timeout, or unhandled event prints
nothing and exits 0, leaving the call to Claude Code's normal flow. Result-posting is strictly
best-effort — a stash miss or a down daemon is swallowed and the tool proceeds untouched. The
governor can add friction (deny / ask) at PreToolUse but never removes the host's own safety.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from . import client, effectors, pending, transcript


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


def completed_from_tool_response(tool_response: Any) -> bool | None:
    """Best-effort read of whether the tool completed without error. Claude Code exposes no
    universal success flag on PostToolUse, so we inspect the common structural error indicators
    and default to True (the tool ran) when none is present; None when there is no response body
    at all (the outcome is genuinely unknown)."""
    if tool_response is None:
        return None
    if isinstance(tool_response, dict):
        if tool_response.get("is_error") is True or tool_response.get("isError") is True:
            return False
        if tool_response.get("error"):
            return False
        if tool_response.get("success") is False:
            return False
        if tool_response.get("interrupted") is True:
            return False
        return True
    return True  # a plain string / other body ⇒ the tool produced a result


def _stash_decision(hook_input: dict[str, Any], result: dict[str, Any]) -> None:
    """Persist the decide-time event_id keyed by the call's identity so the matching
    PostToolUse can correlate to it. No event_id (a fail-open 503 proceed) ⇒ nothing to
    correlate. Best-effort: a stash failure must never break the already-computed decision."""
    event_id = result.get("event_id")
    if not event_id:
        return
    try:
        pending.write_pending(
            str(hook_input.get("session_id") or ""),
            str(hook_input.get("tool_name") or ""),
            hook_input.get("tool_input"),
            str(event_id),
            time.time(),
        )
    except Exception as err:  # noqa: BLE001 — the stash is telemetry; never break a decision
        _debug(f"pending-stash write failed (non-fatal): {err}")


def _handle_pretooluse(hook_input: dict[str, Any]) -> dict[str, Any] | None:
    payload = transcript.session_from_hook(hook_input)
    profile = os.environ.get("CREDENCE_GOVERNOR_PROFILE")
    if profile:
        payload["profile"] = profile
    result = client.decide(payload)
    _stash_decision(hook_input, result)  # correlate the coming PostToolUse to this decision
    action = str(result.get("action") or "proceed")
    category = result.get("category")  # safety|waste — ADVISORY; overridability is policy
    rationale = result.get("rationale")  # the structural "why" — a legible, specific reason
    deny = _deny_categories()          # default empty => every gated decision is overridable
    _debug(f"{payload['tool_name']} -> {action}/{category} deny={set(deny) or '∅'} ({result.get('features')})")
    if _shadow():
        return effectors.shadow_output(action, payload["tool_name"], category, deny, rationale)
    return effectors.pretooluse_output(action, payload["tool_name"], category, deny, rationale)


def _handle_posttooluse(hook_input: dict[str, Any]) -> None:
    """Correlate the completed call to its PreToolUse decision and POST the measured outcome.
    Always returns None (Claude Code proceeds); every step is best-effort telemetry — a stash
    miss posts without an event_id (the daemon resolves the fallback), and a down daemon is
    swallowed. Never blocks or fails the tool on a result-posting problem."""
    try:
        event_id, latency_s = pending.pop_pending(
            str(hook_input.get("session_id") or ""),
            str(hook_input.get("tool_name") or ""),
            hook_input.get("tool_input"),
            time.time(),
        )
    except Exception as err:  # noqa: BLE001 — telemetry correlation; failing open
        _debug(f"pending-stash pop failed (non-fatal): {err}")
        event_id, latency_s = None, None
    payload: dict[str, Any] = {
        "completed": completed_from_tool_response(hook_input.get("tool_response")),
        "latency_s": latency_s,
    }
    if event_id:
        payload["event_id"] = event_id
    try:
        client.post_result(payload)
    except Exception as err:  # noqa: BLE001 — daemon down / timeout; never block the tool
        _debug(f"/result post failed (non-fatal, failing open): {err}")
    return None


def handle(hook_input: dict[str, Any]) -> dict[str, Any] | None:
    """Pure core: a hook payload -> the stdout JSON (or None to defer). PreToolUse may raise
    on daemon failure so `main` can fail open around it; PostToolUse is best-effort and never
    raises (it always defers with None)."""
    name = hook_input.get("hook_event_name") or ""
    if name == "PreToolUse":
        return _handle_pretooluse(hook_input)
    if name == "PostToolUse":
        return _handle_posttooluse(hook_input)
    return None  # any other event (SessionStart, UserPromptSubmit, …) defers


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
