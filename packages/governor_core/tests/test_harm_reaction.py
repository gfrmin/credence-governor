"""A2 — the harm reaction channel: legible rationales + the harm belief learning from
overrides (polarity, safety-gate, burst dedup, restart-durable replay) + compute_cost.

Engine-free: a recording stub session/skin captures the observe/decide calls the daemon
makes, so we assert the wiring without a live brain (the repo's mock-session convention)."""

from __future__ import annotations

import threading

from credence_governor_core.config import HARM
from credence_governor_core.daemon import Daemon, _rationale
from credence_governor_core.log import ObservationLog
from credence_governor_core.session import BrainSession

# A benign 7-tuple harm context; overrides make specific coordinates hot.
_BENIGN = dict(zip(HARM["feature_names"], ["read-only", "none", "none", "none", "none", "no", "no"]))


def _cell(overrides: dict | None = None) -> dict:
    d = dict(_BENIGN)
    if overrides:
        d.update(overrides)
    return d


SAFETY = _cell({"cred-exfil-chain": "yes"})                                  # -> category "safety"
SAFETY2 = _cell({"injected-imperative": "yes", "taint-source": "web"})       # a DIFFERENT safety cell
WASTE = _cell()                                                              # benign -> category "waste"


# ── B1: legible rationales (pure, deterministic — the _block_category pattern) ──
def test_rationale_names_the_credential_exfil_coordinate():
    r = _rationale(SAFETY, "safety")
    assert "credential store" in r and "external host" in r


def test_rationale_names_injection():
    assert "untrusted fetched content" in _rationale(SAFETY2, "safety")


def test_rationale_names_a_steered_privileged_write():
    feats = _cell({"target-sensitivity": "system-privileged", "taint-source": "web"})
    assert "privileged system path" in _rationale(feats, "safety")


def test_rationale_flags_a_loop_when_no_safety_coordinate():
    feats = _cell({"recent-identical-call-count": "ident-2"})
    assert "loop" in _rationale(feats, "waste")


# ── B2: harm learning from overrides ──
class _RecSession:
    def __init__(self):
        self.observed: list[tuple[dict, int]] = []
        self.harm_observed: list[tuple[dict, int]] = []

    def observe(self, features, obs):
        self.observed.append((features, obs))

    def observe_harm(self, features, unsafe):
        self.harm_observed.append((features, unsafe))


def _daemon(tmp_path, sess):
    return Daemon(sess, ObservationLog(str(tmp_path / "obs.jsonl")), threading.Lock())


def _propose(d, event_id, features):
    d.log.append({"event_type": "tool-proposed", "event_id": event_id, "features": features})


def test_safety_approve_teaches_harm_safe_with_inverse_polarity(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    res = d.feedback("e1", 1)  # APPROVE (waste obs=1) -> harm obs = 1-1 = 0 (safe)
    assert sess.observed == [(SAFETY, 1)]              # general belief always learns
    assert sess.harm_observed == [(SAFETY, 0)]         # polarity inverted
    assert res["category"] == "safety" and res["harm_observation"] == 0


def test_safety_reject_teaches_harm_unsafe(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    res = d.feedback("e1", 0)  # REJECT (waste obs=0) -> harm obs = 1 (unsafe)
    assert sess.harm_observed == [(SAFETY, 1)]
    assert res["harm_observation"] == 1


def test_waste_override_does_not_touch_the_harm_belief(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", WASTE)
    res = d.feedback("e1", 0)  # a reject on a benign/waste gate is wastefulness, not harm
    assert sess.observed == [(WASTE, 0)]
    assert sess.harm_observed == []
    assert res["category"] == "waste" and res["harm_observation"] is None


def test_burst_of_identical_safety_verdicts_counts_once(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    _propose(d, "e2", SAFETY)  # SAME cell
    d.feedback("e1", 1)
    d.feedback("e2", 1)  # consecutive identical verdict on the same cell -> deduped
    assert sess.harm_observed == [(SAFETY, 0)]         # only the first conditioned
    assert sess.observed == [(SAFETY, 1), (SAFETY, 1)]  # the general belief still learns both


def test_alternating_verdict_on_same_cell_is_not_deduped(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    _propose(d, "e2", SAFETY)
    d.feedback("e1", 1)  # harm 0
    d.feedback("e2", 0)  # harm 1 — operator corrected; different verdict -> conditioned
    assert sess.harm_observed == [(SAFETY, 0), (SAFETY, 1)]


def test_different_safety_cells_are_not_deduped(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    _propose(d, "e2", SAFETY2)
    d.feedback("e1", 1)
    d.feedback("e2", 1)  # different cell -> both conditioned
    assert sess.harm_observed == [(SAFETY, 0), (SAFETY2, 0)]


def test_deduped_verdict_is_audited_but_not_replayable(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    _propose(d, "e2", SAFETY)
    d.feedback("e1", 1)
    d.feedback("e2", 1)
    recs = [r for r in d.log.read() if r.get("event_type") == "user-responded"]
    assert recs[0].get("harm_observation") == 0 and "harm_deduped" not in recs[0]
    assert recs[1].get("harm_deduped") == 0 and recs[1].get("harm_observation") is None
    # replay sees only the conditioned one — so live == replay (the burst stays collapsed).
    assert d.log.replay_harm_contexts() == [{"features": SAFETY, "unsafe": 0}]


def test_user_responded_record_carries_the_audit_fields(tmp_path):
    sess = _RecSession()
    d = _daemon(tmp_path, sess)
    _propose(d, "e1", SAFETY)
    d.feedback("e1", 0)
    rec = next(r for r in d.log.read() if r.get("event_type") == "user-responded")
    assert rec["category"] == "safety"
    assert "credential store" in rec["rationale_shown"]
    assert rec["harm_observation"] == 1


# ── replay durability (log level) ──
def test_replay_harm_contexts_only_yields_explicit_harm_observations(tmp_path):
    log = ObservationLog(str(tmp_path / "o.jsonl"))
    log.append({"event_type": "tool-proposed", "event_id": "e1", "features": SAFETY})
    log.append({"event_type": "tool-proposed", "event_id": "e2", "features": SAFETY2})
    log.append({"event_type": "tool-proposed", "event_id": "e3", "features": WASTE})
    log.append({"event_type": "user-responded", "in_response_to": "e1", "harm_observation": 1})
    log.append({"event_type": "user-responded", "in_response_to": "e2", "harm_deduped": 0})   # audit-only
    log.append({"event_type": "user-responded", "in_response_to": "e3", "response": "no"})     # pre-A2 shape
    assert log.replay_harm_contexts() == [{"features": SAFETY, "unsafe": 1}]


def test_boot_replays_harm_overrides(tmp_path):
    # A recording skin + a minimal harm brain so boot() sets self.harm and replays the log.
    (tmp_path / "harm_brain.counts.json").write_text(
        '{"feature_names": %s, "contexts": []}' % list(HARM["feature_names"]).__repr__().replace("'", '"')
    )
    log = ObservationLog(str(tmp_path / "obs.jsonl"))
    log.append({"event_type": "tool-proposed", "event_id": "e1", "features": SAFETY})
    log.append({"event_type": "user-responded", "in_response_to": "e1", "harm_observation": 1})

    class _RecSkin:
        def __init__(self):
            self.calls = []
            self._bma = 0

        def initialize(self):
            return {"version": "0.1.0", "protocol": "1.12",
                    "methods": ["structure_bma", "structure_observe", "structure_decide",
                                "routing_init", "routing_decide", "routing_outcome"]}

        def _call(self, method, params):
            self.calls.append((method, params))
            if method == "structure_bma":
                self._bma += 1
                tag = "waste" if self._bma == 1 else "harm"
                return {"model_id": f"{tag}_m", "state_id": f"{tag}_s"}
            if method == "routing_init":
                return {"routing_state_id": "r"}
            return {"state_id": "s"}

    sess = BrainSession(_RecSkin(), str(tmp_path), log)
    sess.boot()
    harm_obs = [p for m, p in sess.skin.calls
                if m == "structure_observe" and p.get("state_id") == "harm_s"]
    assert harm_obs == [{"model_id": "harm_m", "state_id": "harm_s", "features": SAFETY, "observation": 1}]


# ── compute_cost (the one currency term wired here) ──
class _DecSkin:
    def __init__(self):
        self.params = None

    def initialize(self):
        return {}

    def _call(self, _method, params):
        self.params = params
        return {"action": "proceed"}


def _decide_session(tmp_path):
    sess = BrainSession(_DecSkin(), str(tmp_path), ObservationLog(str(tmp_path / "o.jsonl")))
    sess.waste = {"model_id": "m", "state_id": "s"}
    return sess


def test_decide_sends_compute_cost_default_zero_bit_identical(tmp_path):
    sess = _decide_session(tmp_path)
    sess.decide(_cell())
    assert sess.skin.params["compute_cost"] == 0.0  # default 0 ⇒ pre-compute decision unchanged


def test_decide_compute_cost_is_profile_overridable_and_top_level(tmp_path):
    sess = _decide_session(tmp_path)
    sess.decide(_cell(), profile={"compute_cost": 0.005})
    assert sess.skin.params["compute_cost"] == 0.005  # top-level, not inside the harm coordinate
