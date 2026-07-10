"""test_shadow_wiring.py — the daemon's shadow mirror: every live
decide/verdict/outcome reaches the shadow's submit surface with the right
payload, the good-bit rule gates outcome submits, harm never crosses, and
a misbehaving shadow can never perturb the primary response path.

Mirrors test_result.py's pattern: a real ThreadingHTTPServer on an
ephemeral port, a stub session, a fake shadow, driven via urllib."""

from __future__ import annotations

import json
import threading
import types
import urllib.request

import pytest

from credence_governor_core.daemon import Daemon
from credence_governor_core.log import ObservationLog

# features whose recomputed category is SAFETY (injection, non-own source)
SAFETY_FEATURES = {"tool-name": "bash", "taint-source": "web",
                   "injected-imperative": "yes"}
WASTE_FEATURES = {"tool-name": "bash"}


class FakeShadow:
    def __init__(self, raise_on_submit=False, on_submit=None):
        self.decides: list[tuple] = []
        self.verdicts: list[tuple] = []
        self.outcomes: list[tuple] = []
        self.raise_on_submit = raise_on_submit
        self.on_submit = on_submit

    def _guard(self):
        if self.on_submit is not None:
            self.on_submit()
        if self.raise_on_submit:
            raise RuntimeError("shadow exploded")

    def submit_decide(self, event_id, features, profile=None):
        self._guard()
        self.decides.append((event_id, dict(features), profile))

    def submit_verdict(self, features, observation):
        self._guard()
        self.verdicts.append((dict(features), observation))

    def submit_outcome(self, event_id, features, good):
        self._guard()
        self.outcomes.append((event_id, dict(features), good))

    def stats(self):
        return {"queue": 0, "drops": 0, "forms": {"latent@1": {"alive": True}}}


def make_daemon(tmp_path, shadow, observed=None):
    session = types.SimpleNamespace(
        decide=lambda features, harm, profile=None: "block",
        observe=lambda features, obs: (observed or []).append(("waste", obs)),
        observe_harm=lambda features, unsafe: (observed or []).append(("harm", unsafe)),
        route_outcome=lambda model, features, success: None,
    )
    log = ObservationLog(str(tmp_path / "obs.jsonl"))
    daemon = Daemon(session, log, threading.Lock(), shadow=shadow)
    daemon.ready.set()
    return daemon, log


@pytest.fixture
def served(tmp_path):
    shadow = FakeShadow()
    daemon, log = make_daemon(tmp_path, shadow)
    httpd = daemon.bind("127.0.0.1", 0)
    daemon.start(httpd)
    port = httpd.server_address[1]
    try:
        yield daemon, port, log, shadow
    finally:
        httpd.shutdown()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        method="POST", headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, json.loads(r.read())


def test_decide_mirrors_after_the_log_appends(tmp_path):
    """The shadow decide fires only once its membrane-shadow join target
    (the tool-proposed record) is on the log."""
    log_types_at_submit: list[list[str]] = []
    shadow = FakeShadow()
    daemon, log = make_daemon(tmp_path, shadow)
    shadow.on_submit = lambda: log_types_at_submit.append(
        [r["event_type"] for r in log.read()])
    out = daemon.decide_sync({"event_id": "e1", "features": WASTE_FEATURES,
                              "profile": {"cost": 2.0}})
    assert out["action"] == "block"
    assert shadow.decides == [("e1", WASTE_FEATURES, {"cost": 2.0})]
    assert log_types_at_submit == [["tool-proposed", "decision"]]


def test_sse_dispatch_mirrors_decide(tmp_path):
    shadow = FakeShadow()
    daemon, _log = make_daemon(tmp_path, shadow)
    daemon.dispatch({"event_type": "tool-proposed", "event_id": "e2",
                     "features": WASTE_FEATURES})
    assert shadow.decides == [("e2", WASTE_FEATURES, None)]


def test_feedback_mirrors_waste_verdict_only(served):
    """A SAFETY-category verdict conditions the harm overlay on the
    primary but the shadow sees only the WASTE observation — the harm
    coordinate never crosses (epoch 1)."""
    daemon, port, log, shadow = served
    log.append({"event_type": "tool-proposed", "event_id": "e1",
                "features": SAFETY_FEATURES})
    log.append({"event_type": "decision", "in_response_to": "e1", "action": "block"})
    code, body = _post(port, "/feedback", {"event_id": "e1", "observation": 0})
    assert code == 200 and body["ok"]
    assert body["category"] == "safety"
    assert body["harm_observation"] == 1          # the primary learned harm
    assert shadow.verdicts == [(SAFETY_FEATURES, 0)]  # the shadow got waste only
    assert shadow.outcomes == []


def test_result_good_bit_rule_gates_the_outcome_mirror(served):
    daemon, port, log, shadow = served
    for eid in ("kept", "undone", "murky"):
        log.append({"event_type": "tool-proposed", "event_id": eid,
                    "features": {"tool-name": "bash"}})
    _post(port, "/result", {"event_id": "kept", "completed": True})
    _post(port, "/result", {"event_id": "undone", "reverted": True})
    _post(port, "/result", {"event_id": "murky"})          # all observables None
    assert [(e, g) for e, _f, g in shadow.outcomes] == [("kept", 1), ("undone", 0)]
    # features joined from the decide-time record (log fallback path here)
    assert shadow.outcomes[0][1] == {"tool-name": "bash"}


def test_result_without_features_on_record_skips(served):
    daemon, port, _log, shadow = served
    # event never proposed: no features anywhere → no outcome submit
    _post(port, "/result", {"event_id": "ghost", "completed": True})
    assert shadow.outcomes == []


def test_tool_completed_mirrors_outcome(tmp_path):
    shadow = FakeShadow()
    daemon, log = make_daemon(tmp_path, shadow)
    log.append({"event_type": "tool-proposed", "event_id": "evt_a",
                "features": {"tool-name": "grep"}})
    daemon.dispatch({
        "event_type": "tool-completed", "session_id": "s1",
        "in_response_to": "evt_a",
        "outcome": {"success": True, "duration_ms": 250},
    })
    assert shadow.outcomes == [("evt_a", {"tool-name": "grep"}, 1)]


def test_raising_shadow_never_perturbs_the_primary(tmp_path):
    shadow = FakeShadow(raise_on_submit=True)
    daemon, log = make_daemon(tmp_path, shadow)
    httpd = daemon.bind("127.0.0.1", 0)
    daemon.start(httpd)
    port = httpd.server_address[1]
    try:
        code, body = _post(port, "/decide", {"event_id": "e1",
                                             "features": WASTE_FEATURES})
        assert code == 200 and body["action"] == "block"   # primary intact
        code, body = _post(port, "/result", {"event_id": "e1", "completed": True})
        assert code == 200 and body["ok"]
        log.append({"event_type": "tool-proposed", "event_id": "e2",
                    "features": WASTE_FEATURES})
        log.append({"event_type": "decision", "in_response_to": "e2", "action": "ask"})
        code, body = _post(port, "/feedback", {"event_id": "e2", "observation": 1})
        assert code == 200 and body["ok"]
    finally:
        httpd.shutdown()


def test_report_carries_shadow_stats_only_when_present(tmp_path):
    shadow = FakeShadow()
    daemon, _log = make_daemon(tmp_path, shadow)
    assert daemon.report()["membrane_shadow"]["forms"]["latent@1"]["alive"] is True
    daemon_none, _log2 = make_daemon(tmp_path, None)
    assert "membrane_shadow" not in daemon_none.report()


def test_features_cache_serves_the_outcome_join(tmp_path):
    """After a decide, the outcome join reads the in-memory cache — no
    log scan (the log is truncated to prove the read never happens)."""
    shadow = FakeShadow()
    daemon, log = make_daemon(tmp_path, shadow)
    daemon.decide_sync({"event_id": "e1", "features": WASTE_FEATURES})
    # wipe the log: a fallback log read would now find nothing
    open(log.log_path, "w").close()
    daemon.result_sync({"event_id": "e1", "completed": True})
    assert shadow.outcomes == [("e1", WASTE_FEATURES, 1)]
