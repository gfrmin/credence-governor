# Role: eval
"""Synthetic-transcript tests for the outcome-grounding engine.

Builds a tiny capture JSONL with hand-laid sessions and asserts the structural
classifier reads each call's fate correctly — and that cap-{i} indices stay aligned
through the truncated-skip + event_id-dedup filters load_capture also applies.
"""

from __future__ import annotations

import json

import outcomes as O


def _msg(role, **kw):
    return {"role": role, **kw}


def _rec(eid, tool, inp, root, messages, truncated=False):
    return {"event_id": eid, "tool_name": tool, "input": inp, "truncated": truncated,
            "session": {"project_root": root, "messages": messages}}


# S1 — a benign session: `Bash ls` (X) then `Read a.py` (Y), then more work.
M1 = [
    _msg("user", timestamp="T1-0"),
    _msg("assistant", timestamp="T1-1"),
    _msg("tool_call", tool_name="Bash", input={"command": "ls"}, timestamp="T1-2"),     # X
    _msg("tool_result", tool_name="Bash", result="a\nb", timestamp="T1-3"),
    _msg("assistant", timestamp="T1-4"),
    _msg("tool_call", tool_name="Read", input={"file_path": "a.py"}, timestamp="T1-5"),  # Y
    _msg("tool_result", result="code", timestamp="T1-6"),
]
# S2 — a write that gets reverted: `Write f.py` (X) then `git restore f.py`.
M2 = [
    _msg("user", timestamp="T2-0"),
    _msg("tool_call", tool_name="Write", input={"file_path": "f.py", "content": "x"}, timestamp="T2-1"),
    _msg("tool_result", result="ok", timestamp="T2-2"),
    _msg("assistant", timestamp="T2-3"),
    _msg("tool_call", tool_name="Bash", input={"command": "git restore f.py"}, timestamp="T2-4"),
    _msg("tool_result", result="", timestamp="T2-5"),
]


def _capture(tmp_path):
    recs = [
        _rec("e0", "Bash", {"command": "ls"}, "p1", M1[:2]),                 # idx0  X gate (accepted)
        _rec("e1", "Read", {"file_path": "a.py"}, "p1", M1[:5]),             # idx1  Y gate (ambiguous: no follow-on)
        _rec("e2", "Bash", {"command": "echo done"}, "p1", M1[:7]),          # idx2  final S1 (ambiguous: unobserved tail)
        _rec("e3", "Write", {"file_path": "f.py", "content": "x"}, "p2", M2[:1]),  # idx3  reverted
        _rec("e4", "Bash", {"command": "echo k"}, "p2", M2[:6]),             # idx4  final S2
        _rec("tt", "Bash", {"command": "x"}, "p2", M2[:6], truncated=True),  # skipped (truncated)
        _rec("e0", "Bash", {"command": "ls"}, "p1", M1[:2]),                 # skipped (dup event_id)
        _rec("e5", "Bash", {"command": "pwd"}, "p3", [_msg("user", timestamp="T3-0"),
                                                      _msg("assistant", timestamp="T3-1")]),  # idx5 singleton
    ]
    p = tmp_path / "cap.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(p)


def test_index_alignment_survives_filters(tmp_path):
    si = O.SessionIndex.build(_capture(tmp_path))
    # truncated + dup dropped → 6 calls, indices 0..5 (cap-5 is the singleton, not the dup).
    assert sorted(si.calls) == [0, 1, 2, 3, 4, 5]
    assert si.calls[5]["event"]["input"] == {"command": "pwd"}


def test_accepted(tmp_path):
    o = O.SessionIndex.build(_capture(tmp_path)).classify(0)
    assert o.label == "accepted" and o.executed and o.continued


def test_ambiguous_no_followon_and_unobserved_tail(tmp_path):
    si = O.SessionIndex.build(_capture(tmp_path))
    assert si.classify(1).label == "ambiguous"   # Y ran but nothing after it
    assert si.classify(2).label == "ambiguous"   # final snapshot — tail unobserved
    assert si.classify(5).label == "ambiguous"   # singleton session


def test_reverted(tmp_path):
    o = O.SessionIndex.build(_capture(tmp_path)).classify(3)
    assert o.label == "reverted"


def test_ground_returns_requested_cids(tmp_path):
    g = O.SessionIndex.build(_capture(tmp_path)).ground(["cap-0", "cap-3"])
    assert set(g) == {"cap-0", "cap-3"}
    assert g["cap-0"].label == "accepted" and g["cap-3"].label == "reverted"


def test_revert_detector_precision():
    src = {"file_path": "/p/src/a.py", "content": "x"}
    # genuine reverts of the exact target
    assert O._is_revert_of({"input": {"command": "git restore /p/src/a.py"}}, src)
    assert O._is_revert_of({"input": {"command": "rm -f /p/src/a.py"}}, src)
    # forward progress that merely FOLLOWS an edit must NOT read as a revert
    assert not O._is_revert_of({"input": {"command": "cd /p && rm -rf dist build *.egg-info"}}, src)
    assert not O._is_revert_of({"input": {"command": "docker compose -f /p/docker-compose.yml down"}},
                               {"file_path": "/p/docker-compose.yml"})
    assert not O._is_revert_of({"input": {"command": "git commit -m wip"}}, src)


def test_error_marker_detection():
    assert O._is_error("Traceback (most recent call last):")
    assert O._is_error("fatal: not a git repository")
    assert not O._is_error("all tests passed, 0 errors reported")  # bare word must not trip it
