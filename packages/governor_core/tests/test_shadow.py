"""test_shadow.py — the MembraneShadow subsystem's isolation contract:
enqueue-only never-raise submits, worker-owned sessions, the
membrane-shadow record shape, bounded respawns, snapshot boot replay.
All hermetic: fake sessions, no subprocess, no engine."""

import time

from credence_governor_core.log import ObservationLog
from credence_governor_core.shadow import MembraneShadow, build_shadow_from_env


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeClient:
    def __init__(self):
        self.shutdowns = 0

    def shutdown(self):
        self.shutdowns += 1


class FakeSession:
    def __init__(self, action="block", readouts=None, boot_error=None):
        self.client = FakeClient()
        self.action = action
        self.last_readouts = dict(readouts or {})
        self.boot_error = boot_error
        self.booted = False
        self.calls: list[tuple] = []
        self.decide_error: Exception | None = None

    def boot(self):
        if self.boot_error is not None:
            raise self.boot_error
        self.booted = True

    def decide(self, features, harm_features=None, profile=None,
               tail_features=None):
        if self.decide_error is not None:
            raise self.decide_error
        self.calls.append(("decide", features, profile))
        return self.action

    def observe(self, features, observation):
        self.calls.append(("verdict", features, observation))

    def observe_outcome(self, event_id, features, good):
        self.calls.append(("outcome", event_id, features, good))


def make_shadow(tmp_path, forms, **kw):
    log = ObservationLog(str(tmp_path / "log.jsonl"))
    shadow = MembraneShadow(forms, log, logline=lambda _m: None, **kw)
    return log, shadow


def test_decide_appends_the_shadow_record(tmp_path):
    sess = FakeSession(action="block",
                       readouts={"p1": 0.5, "entropy_bits": 3.2,
                                 "residual_mean": 0.42, "sensitivity": True,
                                 "not_a_readout": "dropped"})
    log, shadow = make_shadow(tmp_path, [("latent@1", lambda _snap: sess)])
    shadow.start()
    try:
        shadow.submit_decide("evt_1", {"tool-name": "bash"}, None)
        assert wait_for(lambda: any(
            r.get("event_type") == "membrane-shadow" for r in log.read()))
        rec = [r for r in log.read() if r["event_type"] == "membrane-shadow"][0]
        assert rec["in_response_to"] == "evt_1"
        assert rec["utility_form"] == "latent@1"
        assert rec["action"] == "block"
        assert isinstance(rec["latency_ms"], float)
        # readouts copied verbatim but filtered to the wire's declared set
        assert rec["readouts"] == {"p1": 0.5, "entropy_bits": 3.2,
                                   "residual_mean": 0.42, "sensitivity": True}
        assert shadow.stats()["forms"]["latent@1"]["decides"] == 1
    finally:
        shadow.close()


def test_dual_forms_each_record_and_fifo_order(tmp_path):
    table, latent = FakeSession(action="proceed"), FakeSession(action="block")
    log, shadow = make_shadow(
        tmp_path,
        [("table@1", lambda _s: table), ("latent@1", lambda _s: latent)])
    shadow.start()
    try:
        shadow.submit_decide("e1", {"tool-name": "bash"})
        shadow.submit_verdict({"tool-name": "bash"}, 1)
        shadow.submit_outcome("e1", {"tool-name": "bash"}, 0)
        assert wait_for(lambda: len(latent.calls) == 3 and len(table.calls) == 3)
        # FIFO: arrival order == dispatch order, per form
        assert [c[0] for c in table.calls] == ["decide", "verdict", "outcome"]
        assert [c[0] for c in latent.calls] == ["decide", "verdict", "outcome"]
        recs = [r for r in log.read() if r["event_type"] == "membrane-shadow"]
        assert {(r["utility_form"], r["action"]) for r in recs} == {
            ("table@1", "proceed"), ("latent@1", "block")}
    finally:
        shadow.close()


def test_session_exception_marks_dead_and_never_raises(tmp_path):
    sess = FakeSession()
    sess.decide_error = RuntimeError("engine died")
    _log, shadow = make_shadow(
        tmp_path, [("latent@1", lambda _s: sess)],
        max_respawns=0)
    shadow.start()
    try:
        shadow.submit_decide("e1", {"tool-name": "bash"})  # must not raise
        assert wait_for(
            lambda: shadow.stats()["forms"]["latent@1"]["errors"] == 1)
        st = shadow.stats()["forms"]["latent@1"]
        assert st["alive"] is False
        assert sess.client.shutdowns == 1
        # further submits are still safe no-ops for the dead form
        shadow.submit_decide("e2", {"tool-name": "bash"})
        shadow.submit_verdict({"tool-name": "bash"}, 1)
    finally:
        shadow.close()


def test_respawn_policy_bounded(tmp_path):
    sessions: list[FakeSession] = []

    def factory(_snap):
        s = FakeSession()
        s.decide_error = RuntimeError("always dies")
        sessions.append(s)
        return s

    _log, shadow = make_shadow(
        tmp_path, [("latent@1", factory)],
        max_respawns=2, respawn_backoff_s=0.0)
    shadow.start()
    try:
        for i in range(6):
            shadow.submit_decide(f"e{i}", {"tool-name": "bash"})
            time.sleep(0.05)
        # initial spawn + at most 2 respawns, then permanently dead
        assert wait_for(
            lambda: shadow.stats()["forms"]["latent@1"]["respawns"] == 2)
        time.sleep(0.3)
        assert len(sessions) == 3
        assert shadow.stats()["forms"]["latent@1"]["alive"] is False
    finally:
        shadow.close()


def test_respawn_refreshes_the_snapshot(tmp_path):
    """A respawned session boots from a FRESH snapshot — evidence that
    arrived since daemon start is replayed, not silently lost (PR #26
    review finding)."""
    snapshots: list[list] = []

    def factory(snapshot):
        snapshots.append(snapshot.read())
        s = FakeSession()
        if len(snapshots) == 1:
            s.decide_error = RuntimeError("first session dies")
        return s

    log, shadow = make_shadow(tmp_path, [("latent@1", factory)],
                              max_respawns=1, respawn_backoff_s=0.0)
    log.append({"event_type": "tool-proposed", "event_id": "pre",
                "features": {"tool-name": "bash"}})
    shadow.start()
    try:
        assert wait_for(lambda: len(snapshots) == 1)
        # evidence arrives after start, then the first session dies
        log.append({"event_type": "user-responded", "in_response_to": "pre",
                    "response": "yes"})
        shadow.submit_decide("e1", {"tool-name": "bash"})   # kills session 1
        assert wait_for(lambda: len(snapshots) == 2)
        assert [r["event_type"] for r in snapshots[0]] == ["tool-proposed"]
        assert [r["event_type"] for r in snapshots[1]] == [
            "tool-proposed", "user-responded"]              # refreshed
        assert wait_for(lambda: shadow.stats()["forms"]["latent@1"]
                        ["snapshot_records"] == 2)
    finally:
        shadow.close()


def test_boot_failure_counts_and_other_form_survives(tmp_path):
    healthy = FakeSession(action="proceed")
    log, shadow = make_shadow(
        tmp_path,
        [("table@1", lambda _s: healthy),
         ("latent@1", lambda _s: FakeSession(boot_error=RuntimeError("no binary")))],
        max_respawns=0)
    shadow.start()
    try:
        shadow.submit_decide("e1", {"tool-name": "bash"})
        assert wait_for(lambda: len(healthy.calls) == 1)
        forms = shadow.stats()["forms"]
        assert forms["table@1"]["alive"] is True
        assert forms["latent@1"]["alive"] is False
        recs = [r for r in log.read() if r["event_type"] == "membrane-shadow"]
        assert [r["utility_form"] for r in recs] == ["table@1"]
    finally:
        shadow.close()


def test_queue_full_drops_counted_not_raised(tmp_path):
    # worker never started: the queue can only fill
    _log, shadow = make_shadow(
        tmp_path, [("latent@1", lambda _s: FakeSession())], queue_max=1)
    shadow.submit_decide("e1", {"tool-name": "bash"})
    shadow.submit_decide("e2", {"tool-name": "bash"})  # full: dropped
    assert shadow.stats()["drops"] == 1
    assert shadow.stats()["queue"] == 1


def test_boot_replays_the_start_snapshot_not_later_appends(tmp_path):
    seen_snapshots = []

    def factory(snapshot):
        seen_snapshots.append(snapshot.read())
        return FakeSession()

    log, shadow = make_shadow(tmp_path, [("latent@1", factory)])
    log.append({"event_type": "tool-proposed", "event_id": "pre",
                "features": {"tool-name": "bash"}})
    shadow.start()  # snapshot taken synchronously here
    log.append({"event_type": "tool-proposed", "event_id": "post",
                "features": {"tool-name": "edit"}})
    try:
        assert wait_for(lambda: len(seen_snapshots) == 1)
        assert [r["event_id"] for r in seen_snapshots[0]] == ["pre"]
    finally:
        shadow.close()


def test_build_shadow_from_env(tmp_path, monkeypatch):
    log = ObservationLog(str(tmp_path / "log.jsonl"))
    monkeypatch.delenv("CREDENCE_MEMBRANE_COMMAND", raising=False)
    assert build_shadow_from_env(str(tmp_path), log) is None

    monkeypatch.setenv("CREDENCE_MEMBRANE_COMMAND", "/bin/true")
    monkeypatch.setenv("CREDENCE_MEMBRANE_UTILITY", "table@1, latent@1, table@1")
    shadow = build_shadow_from_env(str(tmp_path), log, logline=lambda _m: None)
    assert shadow is not None
    assert list(shadow.stats()["forms"]) == ["table@1", "latent@1"]  # deduped

    monkeypatch.setenv("CREDENCE_MEMBRANE_UTILITY", "steps@2")
    try:
        build_shadow_from_env(str(tmp_path), log)
    except ValueError as err:
        assert "steps@2" in str(err)
    else:
        raise AssertionError("unknown utility form must fail loudly")
