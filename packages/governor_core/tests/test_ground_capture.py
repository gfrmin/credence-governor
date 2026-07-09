"""ground_capture: backfill structural outcome records for gated calls from the raw capture.

Synthetic capture + log fixtures (the test_outcomes.py pattern): hand-laid sessions whose
fate the structural classifier reads, joined to gated event_ids in the observation log by
event_id. Asserts the appended outcome records, the retry heuristic, incremental skip, and
dry-run.
"""

from __future__ import annotations

import json

from credence_governor_core.log import ObservationLog
from credence_governor_core.training.ground_capture import ground, main


def _msg(role, **kw):
    return {"role": role, **kw}


def _rec(eid, tool, inp, root, messages):
    return {"event_id": eid, "tool_name": tool, "input": inp, "truncated": False,
            "session": {"project_root": root, "messages": messages}}


# S1 — Bash ls (accepted: session continues), Read a.py (ambiguous), more work.
M1 = [
    _msg("user", timestamp="T1-0"),
    _msg("assistant", timestamp="T1-1"),
    _msg("tool_call", tool_name="Bash", input={"command": "ls"}, timestamp="T1-2"),
    _msg("tool_result", result="a\nb", timestamp="T1-3"),
    _msg("assistant", timestamp="T1-4"),
    _msg("tool_call", tool_name="Read", input={"file_path": "a.py"}, timestamp="T1-5"),
    _msg("tool_result", result="code", timestamp="T1-6"),
]
# S2 — Write f.py then git restore f.py (reverted).
M2 = [
    _msg("user", timestamp="T2-0"),
    _msg("tool_call", tool_name="Write", input={"file_path": "f.py", "content": "x"}, timestamp="T2-1"),
    _msg("tool_result", result="ok", timestamp="T2-2"),
    _msg("assistant", timestamp="T2-3"),
    _msg("tool_call", tool_name="Bash", input={"command": "git restore f.py"}, timestamp="T2-4"),
    _msg("tool_result", result="", timestamp="T2-5"),
]
# S3 — Bash badcmd errors, then an identical retry, then a Read (errored + retries=1).
M3 = [
    _msg("user", timestamp="T3-0"),
    _msg("assistant", timestamp="T3-1"),
    _msg("tool_call", tool_name="Bash", input={"command": "badcmd"}, timestamp="T3-2"),
    _msg("tool_result", result="bash: badcmd: command not found", timestamp="T3-3"),
    _msg("assistant", timestamp="T3-4"),
    _msg("tool_call", tool_name="Bash", input={"command": "badcmd"}, timestamp="T3-5"),  # retry
    _msg("tool_result", result="bash: badcmd: command not found", timestamp="T3-6"),
    _msg("assistant", timestamp="T3-7"),
    _msg("tool_call", tool_name="Read", input={"file_path": "z"}, timestamp="T3-8"),
    _msg("tool_result", result="ok", timestamp="T3-9"),
]


def _capture(tmp_path):
    recs = [
        _rec("e_accept", "Bash", {"command": "ls"}, "p1", M1[:2]),
        _rec("e_amb", "Read", {"file_path": "a.py"}, "p1", M1[:5]),
        _rec("e_p1_final", "Bash", {"command": "echo done"}, "p1", M1),       # provides p1's longest transcript
        _rec("e_revert", "Write", {"file_path": "f.py", "content": "x"}, "p2", M2[:1]),
        _rec("e_p2_final", "Bash", {"command": "echo k"}, "p2", M2),          # p2 longest
        _rec("e_err", "Bash", {"command": "badcmd"}, "p3", M3[:2]),
        _rec("e_p3_final", "Read", {"file_path": "z"}, "p3", M3),             # p3 longest
    ]
    p = tmp_path / "cap.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(p)


def _log(tmp_path):
    """An observation log with gated calls (tool-proposed) — one (e_missing) absent from the
    capture, to exercise the unmatched path."""
    path = str(tmp_path / "obs.jsonl")
    log = ObservationLog(path)
    for eid in ("e_accept", "e_revert", "e_err", "e_missing"):
        log.append({"event_type": "tool-proposed", "event_id": eid, "features": {"tool-name": "x"}})
        log.append({"event_type": "decision", "in_response_to": eid, "action": "block"})
    return path


def _outcomes(path):
    return [r for r in ObservationLog(path).read()
            if r.get("event_type") == "outcome" and r.get("source") == "grounding"]


def test_ground_appends_measured_outcomes(tmp_path):
    cap, log_path = _capture(tmp_path), _log(tmp_path)
    tally = ground(cap, log_path)
    by_id = {r["in_response_to"]: r for r in _outcomes(log_path)}

    assert by_id["e_accept"]["source"] == "grounding"
    assert by_id["e_accept"]["completed"] is True and by_id["e_accept"]["reverted"] is False
    assert by_id["e_accept"]["retries"] == 0

    assert by_id["e_revert"]["reverted"] is True          # a later git restore undid it

    # an errored call that was retried once: not completed, retries counted
    assert by_id["e_err"]["completed"] is False and by_id["e_err"]["retries"] == 1

    # a gated call absent from the capture is never grounded
    assert "e_missing" not in by_id

    assert tally["accepted"] == 2 and tally["reverted"] == 1 and tally["unmatched"] == 1


def test_ground_is_incremental(tmp_path):
    cap, log_path = _capture(tmp_path), _log(tmp_path)
    ground(cap, log_path)
    tally2 = ground(cap, log_path)
    # everything already carries a grounding outcome ⇒ all skipped, nothing re-classified
    assert tally2["skipped"] == 3 and tally2["accepted"] == 0 and tally2["reverted"] == 0
    # and no duplicate outcome records were appended
    assert len(_outcomes(log_path)) == 3


def test_ground_dry_run_writes_nothing(tmp_path):
    cap, log_path = _capture(tmp_path), _log(tmp_path)
    before = ObservationLog(log_path).read()
    tally = ground(cap, log_path, dry_run=True)
    assert ObservationLog(log_path).read() == before      # log untouched
    assert tally["accepted"] == 2 and tally["reverted"] == 1


def test_main_exits_zero_and_tallies(tmp_path, capsys):
    cap, log_path = _capture(tmp_path), _log(tmp_path)
    rc = main(["--capture", cap, "--log", log_path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "grounded" in out and "accepted=2" in out
