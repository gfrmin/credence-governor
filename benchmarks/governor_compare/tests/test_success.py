# Role: eval
"""test_success.py — Phase 3 success-axis invariants (pure metric math + SWE-bench synthesis).

No skin / daemon / network: the metric core (success.py) is pure, and swebench.py synthesis
runs off the committed fixture. The honest claims rest on these holding."""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import success as SU  # noqa: E402


def _v(cid, decision, hard):
    return SU.CallVerdict(cid, decision, hard)


# ── working-session denominator ────────────────────────────────────────────────
def test_working_sessions_need_an_accepted_call():
    sessions = {"s1": ["a", "b"], "s2": ["c"], "s3": ["d"]}
    labels = {"a": "accepted", "b": "reverted", "c": "ambiguous", "d": "accepted"}
    w = SU.working_sessions(sessions, labels)
    assert set(w) == {"s1", "s3"}        # s2 (all-ambiguous) carries no landed-work evidence


# ── a break = HARD block on an ACCEPTED call ───────────────────────────────────
def test_hard_block_on_accepted_breaks_the_session():
    sessions = {"s1": ["a", "b"]}
    labels = {"a": "accepted", "b": "accepted"}
    verdicts = {"a": _v("a", "allow", False), "b": _v("b", "block", True)}
    r = SU.aggregate(sessions, labels, verdicts)
    assert r["working_sessions"] == 1
    assert r["broken_sessions"] == 1
    assert r["completion_preserved"] == 0.0


def test_hard_block_on_reverted_or_ambiguous_does_not_break():
    # blocking work the developer themselves undid (or that we never observed) is not a false break
    sessions = {"s1": ["acc", "rev", "amb"]}
    labels = {"acc": "accepted", "rev": "reverted", "amb": "ambiguous"}
    verdicts = {"acc": _v("acc", "allow", False),
                "rev": _v("rev", "block", True),
                "amb": _v("amb", "block", True)}
    r = SU.aggregate(sessions, labels, verdicts)
    assert r["broken_sessions"] == 0
    assert r["completion_preserved"] == 1.0


# ── overridable block / ask = friction, never a break ──────────────────────────
def test_overridable_block_is_friction_not_break():
    sessions = {"s1": ["a"]}
    labels = {"a": "accepted"}
    # credence-style: a block that is NOT hard (overridable-by-default)
    verdicts = {"a": _v("a", "block", False)}
    r = SU.aggregate(sessions, labels, verdicts)
    assert r["broken_sessions"] == 0
    assert r["completion_preserved"] == 1.0
    assert r["friction_sessions"] == 1
    assert r["friction_session_rate"] == 1.0


def test_ask_is_friction_not_break():
    sessions = {"s1": ["a"]}
    labels = {"a": "accepted"}
    verdicts = {"a": _v("a", "ask", False)}
    r = SU.aggregate(sessions, labels, verdicts)
    assert r["broken_sessions"] == 0
    assert r["friction_sessions"] == 1


def test_allow_is_neither_break_nor_friction():
    sessions = {"s1": ["a"]}
    labels = {"a": "accepted"}
    r = SU.aggregate(sessions, labels, {"a": _v("a", "allow", False)})
    assert r["broken_sessions"] == 0 and r["friction_sessions"] == 0
    assert r["completion_preserved"] == 1.0 and r["friction_session_rate"] == 0.0


def test_per_call_rates_over_accepted_only():
    sessions = {"s1": ["a", "b", "c"]}
    labels = {"a": "accepted", "b": "accepted", "c": "reverted"}
    verdicts = {"a": _v("a", "block", True), "b": _v("b", "ask", False), "c": _v("c", "block", True)}
    r = SU.aggregate(sessions, labels, verdicts)
    assert r["accepted_calls"] == 2                  # 'c' (reverted) excluded from denominator
    assert r["hard_break_call_rate"] == 0.5          # only 'a'
    assert r["soft_gate_call_rate"] == 0.5           # only 'b'


def test_soft_gate_property():
    assert _v("x", "ask", False).soft_gate is True
    assert _v("x", "block", False).soft_gate is True   # overridable block
    assert _v("x", "block", True).soft_gate is False   # hard deny is a break, not friction
    assert _v("x", "allow", False).soft_gate is False


# ── SWE-bench gold-trajectory synthesis (off the committed fixture) ────────────
def test_parse_patch_extracts_touched_files_and_added_lines():
    import swebench as SW
    patch = ("diff --git a/pkg/mod.py b/pkg/mod.py\n"
             "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"
             "@@ -1,3 +1,3 @@\n-    old = 1\n+    new = 2\n     keep = 3\n")
    files = SW.parse_patch(patch)
    assert files == [("pkg/mod.py", "    new = 2")]    # '+' line captured, '+++' header excluded


def test_synth_trajectory_shape_and_legitimacy():
    import swebench as SW
    insts = SW.load()
    assert insts, "fixture present"
    calls = SW.synth_trajectory(insts[0])
    # at least one read+edit pair and a trailing pytest bash
    assert any(c.event.tool_name == "edit" for c in calls)
    assert calls[-1].event.tool_name == "bash" and "pytest" in calls[-1].event.input["command"]
    assert all(c.is_harm is False and c.source == "public" for c in calls)
    # cids are task-scoped so each task forms one session
    assert all(c.cid.startswith(insts[0].instance_id + "#") for c in calls)


def test_fixture_is_nontrivial():
    import swebench as SW
    insts = SW.load()
    assert len(insts) >= 20                            # the public anchor is a real sample
    assert all(i.patch and i.instance_id and i.repo for i in insts)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
