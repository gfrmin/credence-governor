"""POST /feedback records a human verdict on a past decision and conditions the governance
belief — the Claude Code analogue of OpenClaw's onResolution → user-responded → observe
(Claude Code's subprocess hook has no resolution callback, so the loop is closed explicitly).

Features are recovered from the log's tool-proposed record (the sync /decide path doesn't
populate the SSE _pending_asks map); the stub session records the observe so no engine is
needed. The appended user-responded record is what replay_contexts() re-applies on boot.
"""

from __future__ import annotations

import json
import threading
import types
import urllib.error
import urllib.request

import pytest

from credence_governor_core.daemon import Daemon
from credence_governor_core.log import ObservationLog


@pytest.fixture
def served(tmp_path):
    observed: list[tuple] = []
    session = types.SimpleNamespace(observe=lambda features, obs: observed.append((features, obs)))
    log = ObservationLog(str(tmp_path / "obs.jsonl"))
    # two prior decisions, as /decide would have logged them
    log.append({"event_type": "tool-proposed", "event_id": "evt_a", "features": {"tool-name": "grep"}})
    log.append({"event_type": "decision", "in_response_to": "evt_a", "action": "block"})
    log.append({"event_type": "tool-proposed", "event_id": "evt_b", "features": {"tool-name": "bash"}})
    log.append({"event_type": "decision", "in_response_to": "evt_b", "action": "ask"})
    # a later PROCEED that "correct the last decision" must NOT shadow the ask that gated.
    log.append({"event_type": "tool-proposed", "event_id": "evt_c", "features": {"tool-name": "read"}})
    log.append({"event_type": "decision", "in_response_to": "evt_c", "action": "proceed"})
    daemon = Daemon(session, log, threading.Lock())
    daemon.ready.set()
    httpd = daemon.bind("127.0.0.1", 0)
    daemon.start(httpd)
    port = httpd.server_address[1]
    try:
        yield daemon, port, observed, log
    finally:
        httpd.shutdown()


def _post(port, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/feedback", data=json.dumps(body).encode(),
        method="POST", headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_feedback_on_event_conditions_recovered_features(served):
    _daemon, port, observed, log = served
    code, body = _post(port, {"event_id": "evt_a", "observation": 1})
    assert code == 200 and body["ok"]
    assert observed == [({"tool-name": "grep"}, 1)]  # recovered + conditioned
    assert any(
        r.get("event_type") == "user-responded" and r.get("in_response_to") == "evt_a"
        and r.get("response") == "yes" and r.get("human")
        for r in log.read()
    )


def test_feedback_last_targets_last_gated_decision_not_a_later_proceed(served):
    _daemon, port, observed, _log = served
    code, body = _post(port, {"observation": 0})  # no event_id -> last GATED (evt_b), not evt_c
    assert code == 200 and body["event_id"] == "evt_b"
    assert observed == [({"tool-name": "bash"}, 0)]


def test_feedback_unknown_event_errors_without_conditioning(served):
    _daemon, port, observed, _log = served
    _code, body = _post(port, {"event_id": "nope", "observation": 1})
    assert not body["ok"]
    assert observed == []  # never condition on an unrecoverable event


def test_feedback_persists_for_boot_replay(served):
    _daemon, port, _observed, log = served
    _post(port, {"event_id": "evt_a", "observation": 1})
    # replay_contexts rejoins user-responded -> tool-proposed features: a reboot reproduces
    # exactly the (features, observation) conditioned live (order-independent => exact).
    assert {"features": {"tool-name": "grep"}, "observation": 1} in log.replay_contexts()
