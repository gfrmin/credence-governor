"""POST /result records a MEASURED outcome for a past decision, linked to it by
in_response_to == the decide-time tool-proposed event_id. The openclaw tool-completed
path records the same shape server-side when the completion names a governance decision.
Outcomes are append-only telemetry — several may share one event_id, and they are inert
for boot replay (log.replay_* filter by event_type).

Mirrors test_feedback.py: a real ThreadingHTTPServer on an ephemeral port, a stub session,
the ObservationLog seeded with hand-written records, driven via urllib.
"""

from __future__ import annotations

import json
import threading
import types
import urllib.request

import pytest

from credence_governor_core.daemon import Daemon
from credence_governor_core.log import ObservationLog


@pytest.fixture
def served(tmp_path):
    routed: list[tuple] = []
    session = types.SimpleNamespace(
        observe=lambda features, obs: None,
        route_outcome=lambda model, features, success: routed.append((model, features, success)),
    )
    log = ObservationLog(str(tmp_path / "obs.jsonl"))
    # two prior gated calls, as /decide would have logged them
    log.append({"event_type": "tool-proposed", "event_id": "evt_a", "features": {"tool-name": "grep"}})
    log.append({"event_type": "decision", "in_response_to": "evt_a", "action": "block"})
    log.append({"event_type": "tool-proposed", "event_id": "evt_b", "features": {"tool-name": "bash"}})
    log.append({"event_type": "decision", "in_response_to": "evt_b", "action": "ask"})
    daemon = Daemon(session, log, threading.Lock())
    daemon.ready.set()
    httpd = daemon.bind("127.0.0.1", 0)
    daemon.start(httpd)
    port = httpd.server_address[1]
    try:
        yield daemon, port, log, routed
    finally:
        httpd.shutdown()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        method="POST", headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, json.loads(r.read())


def _outcomes(log):
    return [r for r in log.read() if r.get("event_type") == "outcome"]


def test_result_with_explicit_event_id(served):
    _daemon, port, log, _routed = served
    code, body = _post(port, "/result", {
        "event_id": "evt_a", "completed": True, "latency_s": 1.5, "spend_usd": 0.02,
    })
    assert code == 200 and body["ok"] and body["event_id"] == "evt_a"
    (rec,) = _outcomes(log)
    assert rec["in_response_to"] == "evt_a"
    assert rec["source"] == "result-hook"
    assert rec["completed"] is True and rec["latency_s"] == 1.5 and rec["spend_usd"] == 0.02
    # unmeasured fields default to None, not absent
    assert rec["reverted"] is None and rec["retries"] is None and rec["error"] is None


def test_result_falls_back_to_last_unanswered_proposal(served):
    _daemon, port, log, _routed = served
    code, body = _post(port, "/result", {"completed": False, "error": "boom"})
    # evt_b is the most recent proposal with no outcome yet
    assert code == 200 and body["event_id"] == "evt_b"
    (rec,) = _outcomes(log)
    assert rec["in_response_to"] == "evt_b" and rec["completed"] is False and rec["error"] == "boom"


def test_result_fallback_skips_already_answered(served):
    _daemon, port, log, _routed = served
    _post(port, "/result", {"event_id": "evt_b", "completed": True})   # answer evt_b explicitly
    _code, body = _post(port, "/result", {"completed": True})          # fallback should pick evt_a now
    assert body["event_id"] == "evt_a"


def test_multiple_outcomes_per_event_allowed(served):
    _daemon, port, log, _routed = served
    _post(port, "/result", {"event_id": "evt_a", "completed": True, "latency_s": 0.9})
    _post(port, "/result", {"event_id": "evt_a", "reverted": True, "retries": 2})
    recs = [r for r in _outcomes(log) if r["in_response_to"] == "evt_a"]
    assert len(recs) == 2
    assert recs[0]["completed"] is True and recs[1]["reverted"] is True and recs[1]["retries"] == 2


def test_tool_completed_records_outcome_when_correlated(served):
    daemon, _port, log, routed = served
    # a governance decision correlated by in_response_to (== the tool-proposed event_id)
    daemon.dispatch({
        "event_type": "tool-completed", "session_id": "s1", "in_response_to": "evt_a",
        "outcome": {"success": True, "duration_ms": 250, "error": None},
    })
    recs = [r for r in _outcomes(log) if r["source"] == "openclaw"]
    assert len(recs) == 1
    assert recs[0]["in_response_to"] == "evt_a"
    assert recs[0]["completed"] is True and recs[0]["latency_s"] == 0.25


def test_tool_completed_without_governance_match_records_no_outcome(served):
    daemon, _port, log, _routed = served
    # a bare tool-call id (the pre-fix openclaw body) matches no proposal → no outcome
    daemon.dispatch({
        "event_type": "tool-completed", "session_id": "s1", "in_response_to": "toolcall_xyz",
        "outcome": {"success": False, "duration_ms": 10},
    })
    assert _outcomes(log) == []


def test_tool_completed_keeps_routing_credit(served):
    daemon, _port, log, routed = served
    # seed a pending route for the session, then complete it
    daemon._pending_routes["s2"] = {"model": "haiku", "features": {"prompt-length": "short"}}
    daemon.dispatch({
        "event_type": "tool-completed", "session_id": "s2", "in_response_to": "evt_b",
        "outcome": {"success": True, "duration_ms": 100},
    })
    # routing was still credited exactly once…
    assert routed == [("haiku", {"prompt-length": "short"}, True)]
    # …AND the decision-linked outcome was recorded
    assert any(r["source"] == "openclaw" and r["in_response_to"] == "evt_b" for r in _outcomes(log))


def test_report_aggregates_outcomes_and_cost(served):
    daemon, port, _log, _routed = served
    _post(port, "/result", {"event_id": "evt_a", "completed": True, "spend_usd": 0.10})
    _post(port, "/result", {"event_id": "evt_b", "completed": False, "reverted": True, "spend_usd": 0.05})
    daemon.log.append({"event_type": "turn-cost", "usd": 1.0})
    daemon.log.append({"event_type": "counterfactual-decision", "effector": "block"})
    rep = daemon.report()
    assert rep["prevented_calls"] == 1              # one block decision
    assert rep["total_events"] == 2                 # two decisions (block + ask)
    assert rep["would_block_calls"] == 1
    assert rep["outcome_records"] == 2
    assert rep["completed"] == 1 and rep["reverted"] == 1
    assert rep["total_usd"] == pytest.approx(1.15)  # 0.10 + 0.05 spend + 1.0 turn-cost
    # existing keys preserved
    assert "events" in rep and rep["decisions"]["block"] == 1


def test_outcomes_are_replay_inert(served):
    _daemon, port, log, _routed = served
    _post(port, "/result", {"event_id": "evt_a", "completed": True, "spend_usd": 0.5})
    # an outcome record is skipped by every replay projection (they filter by event_type)
    assert log.replay_contexts() == []
    assert log.replay_harm_contexts() == []
    assert log.replay_route_outcomes() == []


def test_outcome_records_do_not_perturb_replay(tmp_path):
    """A log with outcome records interspersed replays IDENTICALLY to the same log without
    them — the boot-replay invariance that lets outcomes be added to a live log safely."""
    def seed(log, with_outcomes):
        log.append({"event_type": "tool-proposed", "event_id": "e1", "features": {"tool-name": "grep"}})
        log.append({"event_type": "decision", "in_response_to": "e1", "action": "block"})
        if with_outcomes:
            log.append({"event_type": "outcome", "in_response_to": "e1", "source": "result-hook", "completed": True})
        log.append({"event_type": "user-responded", "in_response_to": "e1", "response": "no", "harm_observation": 1})
        if with_outcomes:
            log.append({"event_type": "outcome", "in_response_to": "e1", "source": "grounding", "reverted": True})
        log.append({"event_type": "route-outcome", "model_id": "haiku", "features": {"p": "short"}, "success": True})

    base = ObservationLog(str(tmp_path / "base.jsonl"))
    mixed = ObservationLog(str(tmp_path / "mixed.jsonl"))
    seed(base, with_outcomes=False)
    seed(mixed, with_outcomes=True)
    assert mixed.replay_contexts() == base.replay_contexts()
    assert mixed.replay_harm_contexts() == base.replay_harm_contexts()
    assert mixed.replay_route_outcomes() == base.replay_route_outcomes()
