"""The daemon binds + serves BEFORE the engine boots (so a duplicate fails fast on
EADDRINUSE instead of booting a second engine); until daemon.ready is set, /ready, /decide
and /sensor answer a fast 503 (fail-open), not a hang. This exercises that gate with a
stub session — no engine needed — by hitting the real HTTP handler on an ephemeral port.
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
    # session.decide must never be reached before ready; assert that if it is.
    session = types.SimpleNamespace(
        decide=lambda *a, **k: (_ for _ in ()).throw(AssertionError("decided before ready"))
    )
    log = ObservationLog(str(tmp_path / "obs.jsonl"))
    daemon = Daemon(session, log, threading.Lock())
    httpd = daemon.bind("127.0.0.1", 0)  # ephemeral port; binds without booting
    daemon.start(httpd)
    port = httpd.server_address[1]
    try:
        yield daemon, port
    finally:
        httpd.shutdown()


def _req(port, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_ready_returns_503_until_booted_then_200(served):
    daemon, port = served
    code, body = _req(port, "/ready")
    assert code == 503 and body["status"] == "booting"
    daemon.ready.set()
    code, body = _req(port, "/ready")
    assert code == 200 and body["status"] == "ready"


def test_decide_503_fail_open_before_ready(served):
    daemon, port = served
    # gate returns 503 with a fail-open proceed, WITHOUT reaching session.decide
    code, body = _req(port, "/decide", method="POST", body={"tool_name": "Bash"})
    assert code == 503
    assert body["action"] == "proceed"  # fast fail-open during boot


def test_sensor_503_before_ready(served):
    daemon, port = served
    code, body = _req(port, "/sensor", method="POST", body={"event_type": "tool-proposed"})
    assert code == 503 and body["status"] == "booting"
