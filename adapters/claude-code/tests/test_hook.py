"""hook.handle: enforce mode applies the decision; CREDENCE_GOVERNOR_SHADOW makes it
observe-only (the daemon still decides + logs, the body never enforces). The decision
and transcript reads are stubbed so this exercises only handle()'s overlay branch."""

from __future__ import annotations

import credence_governor_claude_code.hook as hook


def _stub(monkeypatch, action: str) -> None:
    monkeypatch.setattr(hook.transcript, "session_from_hook", lambda _hi: {"tool_name": "Bash"})
    monkeypatch.setattr(hook.client, "decide", lambda _p: {"action": action, "features": {}})


def test_enforce_mode_blocks_overridably_by_default(monkeypatch):
    # Default policy (no CREDENCE_GOVERNOR_DENY_CATEGORIES): a block is an OVERRIDABLE ask.
    monkeypatch.delenv("CREDENCE_GOVERNOR_SHADOW", raising=False)
    monkeypatch.delenv("CREDENCE_GOVERNOR_DENY_CATEGORIES", raising=False)
    _stub(monkeypatch, "block")
    out = hook.handle({"hook_event_name": "PreToolUse"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_deny_categories_env_makes_block_hard(monkeypatch):
    # An operator opts a category into non-overridable enforcement via the env setting.
    monkeypatch.delenv("CREDENCE_GOVERNOR_SHADOW", raising=False)
    monkeypatch.setenv("CREDENCE_GOVERNOR_DENY_CATEGORIES", "safety")
    monkeypatch.setattr(hook.transcript, "session_from_hook", lambda _hi: {"tool_name": "Bash"})
    monkeypatch.setattr(hook.client, "decide",
                        lambda _p: {"action": "block", "category": "safety", "features": {}})
    out = hook.handle({"hook_event_name": "PreToolUse"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    # a waste block under the same policy stays overridable
    monkeypatch.setattr(hook.client, "decide",
                        lambda _p: {"action": "block", "category": "waste", "features": {}})
    out = hook.handle({"hook_event_name": "PreToolUse"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_shadow_mode_observes_only(monkeypatch):
    monkeypatch.setenv("CREDENCE_GOVERNOR_SHADOW", "1")
    _stub(monkeypatch, "block")
    out = hook.handle({"hook_event_name": "PreToolUse"})
    assert "hookSpecificOutput" not in out  # never enforces in shadow
    assert "Bash" in out["systemMessage"]


def test_shadow_proceed_is_silent(monkeypatch):
    monkeypatch.setenv("CREDENCE_GOVERNOR_SHADOW", "1")
    _stub(monkeypatch, "proceed")
    assert hook.handle({"hook_event_name": "PreToolUse"}) is None


def test_unhandled_event_defers(monkeypatch):
    # Events other than PreToolUse / PostToolUse (SessionStart, UserPromptSubmit, …) defer
    # with no side effects — no decide, no stash, no result post.
    assert hook.handle({"hook_event_name": "UserPromptSubmit"}) is None
    assert hook.handle({}) is None


def test_waste_category_makes_block_overridable(monkeypatch):
    # the hook threads /decide's category through to effectors: a waste block -> ask
    monkeypatch.delenv("CREDENCE_GOVERNOR_SHADOW", raising=False)
    monkeypatch.setattr(hook.transcript, "session_from_hook", lambda _hi: {"tool_name": "Bash"})
    monkeypatch.setattr(hook.client, "decide", lambda _p: {"action": "block", "category": "waste", "features": {}})
    out = hook.handle({"hook_event_name": "PreToolUse"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
