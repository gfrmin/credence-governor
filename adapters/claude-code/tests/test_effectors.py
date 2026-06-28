"""Action -> PreToolUse decision. The governor may only add restriction:
proceed defers (None), ask prompts; "allow" is never emitted.

Overridability is a POLICY (deny_categories), defaulting to all-overridable: every gated
decision is an overridable `ask` unless the operator opted that advisory category into
hard `deny`. The category always shapes the human-facing message. Every enforced decision
carries a user-visible `systemMessage`. `shadow_output` is the observe-only counterpart."""

from __future__ import annotations

from credence_governor_claude_code.effectors import pretooluse_output, shadow_output


def test_proceed_defers_to_host():
    assert pretooluse_output("proceed", "Bash") is None


def test_unknown_action_defers():
    assert pretooluse_output("weird", "Bash") is None


def test_block_defaults_to_overridable_ask():
    # Default policy (empty deny_categories): a block is an OVERRIDABLE ask — the human
    # operator is the final authority, never an un-overridable deny.
    out = pretooluse_output("block", "Bash")
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "ask"
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


# ── overridability policy: all-overridable by default, opt-in hard deny per category ──


def test_all_categories_overridable_by_default():
    # safety, waste, and unclassified all default to an overridable ask.
    for category in ("safety", "waste", None):
        out = pretooluse_output("block", "Bash", category)
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask", category


def test_category_shapes_the_message_even_when_overridable():
    # the advisory category is always reflected in the human-facing reason.
    assert "unsafe" in pretooluse_output("block", "Bash", "safety")["hookSpecificOutput"]["permissionDecisionReason"]
    assert "loop" in pretooluse_output("block", "Bash", "waste")["hookSpecificOutput"]["permissionDecisionReason"]


def test_opt_in_deny_category_is_hard():
    # an operator can make a chosen category non-overridable via deny_categories.
    deny = frozenset({"safety"})
    assert pretooluse_output("block", "Bash", "safety", deny)["hookSpecificOutput"]["permissionDecision"] == "deny"
    # other categories stay overridable
    assert pretooluse_output("block", "Bash", "waste", deny)["hookSpecificOutput"]["permissionDecision"] == "ask"
    # an `ask` action is overridable regardless of policy
    assert pretooluse_output("ask", "Write", "safety", deny)["hookSpecificOutput"]["permissionDecision"] == "ask"


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


def test_shadow_reflects_policy():
    # shadow narration says "would deny" only under an opt-in hard-deny policy, else "ask before".
    assert "ask before" in shadow_output("block", "Bash", "safety")["systemMessage"]
    assert "deny" in shadow_output("block", "Bash", "safety", frozenset({"safety"}))["systemMessage"]
