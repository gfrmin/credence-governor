"""install.py registers BOTH hooks (PreToolUse + SessionStart) idempotently and
removes them cleanly, preserving any unrelated settings."""

from __future__ import annotations

from credence_governor_claude_code import install


def _commands(settings, event):
    return [
        h["command"]
        for entry in settings.get("hooks", {}).get(event, [])
        for h in entry.get("hooks", [])
    ]


def test_add_registers_both_events():
    s = install.add({})
    assert install.HOOK_COMMAND in _commands(s, "PreToolUse")
    assert install.SESSION_START_COMMAND in _commands(s, "SessionStart")
    # PreToolUse carries the all-tools matcher; SessionStart does not
    assert s["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert "matcher" not in s["hooks"]["SessionStart"][0]


def test_add_is_idempotent():
    s = install.add(install.add({}))
    assert _commands(s, "PreToolUse").count(install.HOOK_COMMAND) == 1
    assert _commands(s, "SessionStart").count(install.SESSION_START_COMMAND) == 1


def test_add_preserves_unrelated_settings():
    s = install.add({"model": "opus", "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}
    ]}})
    assert s["model"] == "opus"
    pre = _commands(s, "PreToolUse")
    assert "other-tool" in pre and install.HOOK_COMMAND in pre


def test_remove_clears_both():
    s = install.remove(install.add({}))
    assert _commands(s, "PreToolUse") == []
    assert _commands(s, "SessionStart") == []
