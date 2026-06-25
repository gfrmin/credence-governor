"""Action -> PreToolUse decision. The governor may only add restriction:
proceed defers (None), block denies, ask prompts; "allow" is never emitted."""

from __future__ import annotations

from credence_governor_claude_code.effectors import pretooluse_output


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
