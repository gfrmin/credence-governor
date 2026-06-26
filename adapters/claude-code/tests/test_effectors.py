"""Action -> PreToolUse decision. The governor may only add restriction:
proceed defers (None), block denies, ask prompts; "allow" is never emitted.

Every enforced decision also carries a user-visible `systemMessage` (the
permissionDecisionReason alone is easy to miss). `shadow_output` is the
observe-only counterpart: it never enforces, only narrates what would happen."""

from __future__ import annotations

from credence_governor_claude_code.effectors import pretooluse_output, shadow_output


def test_proceed_defers_to_host():
    assert pretooluse_output("proceed", "Bash") is None


def test_unknown_action_defers():
    assert pretooluse_output("weird", "Bash") is None


def test_block_denies_with_reason():
    out = pretooluse_output("block", "Bash")
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "Bash" in hso["permissionDecisionReason"]


def test_ask_prompts_with_reason():
    out = pretooluse_output("ask", "Write")
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "ask"
    assert "Write" in hso["permissionDecisionReason"]


def test_never_emits_allow():
    for action in ("proceed", "block", "ask", "weird"):
        out = pretooluse_output(action, "X")
        if out is not None:
            assert out["hookSpecificOutput"]["permissionDecision"] != "allow"


# ── visible decisions: a user-facing systemMessage on every enforced decision ──


def test_block_carries_visible_system_message():
    out = pretooluse_output("block", "Bash")
    assert "Bash" in out["systemMessage"]  # shown to the user, not just the model


def test_ask_carries_visible_system_message():
    out = pretooluse_output("ask", "Write")
    assert "Write" in out["systemMessage"]


def test_proceed_has_no_message():
    assert pretooluse_output("proceed", "Bash") is None


# ── shadow mode: observe-only — narrate, never enforce ──


def test_shadow_block_warns_but_does_not_enforce():
    out = shadow_output("block", "Bash")
    assert "Bash" in out["systemMessage"]
    assert "hookSpecificOutput" not in out  # no permissionDecision => the tool proceeds


def test_shadow_ask_warns_but_does_not_enforce():
    out = shadow_output("ask", "Write")
    assert "Write" in out["systemMessage"]
    assert "hookSpecificOutput" not in out


def test_shadow_proceed_is_silent():
    assert shadow_output("proceed", "Bash") is None


def test_shadow_never_enforces():
    for action in ("proceed", "block", "ask", "weird"):
        out = shadow_output(action, "X")
        if out is not None:
            assert "hookSpecificOutput" not in out
