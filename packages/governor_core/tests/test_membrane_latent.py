"""test_membrane_latent.py — the latent@1 generation's hermetic tests
(governance-roadmap Phase 2; membrane-wire.md §6 is the normative wire).
The transport is injected (no process, no engine). These pin the
DECLARED latent block byte-for-byte (a declaration change must be a
visible test change), the stream-tag rules (verdict double-feed,
outcome dedup), the observe_counts warm collapse, and the
pure-choice-relay discipline. The end-to-end path runs only when
CREDENCE_MEMBRANE_COMMAND points at a real driver binary."""

import json
import os

import pytest

from credence_governor_core.config import GOVERNANCE, UTILITY
from credence_governor_core.log import ObservationLog
from credence_governor_core.membrane import (
    MEMBRANE_ENV,
    MembraneError,
    MembraneSession,
    handshake_decl,
    latent_utility_decl,
)

from test_membrane import FakeWire, HANDSHAKE_OK

LATENT_HANDSHAKE_OK = {**HANDSHAKE_OK, "ulatents": 2}


def make_latent_session(tmp_path, replies, brain_dir=None):
    wire = FakeWire(replies)
    log = ObservationLog(str(tmp_path / "log.jsonl"))
    sess = MembraneSession(
        wire.client(),
        brain_dir or str(tmp_path),  # no counts file => no warm collapse
        log,
        logline=lambda _m: None,
        utility_form="latent@1",
    )
    return wire, sess


def test_latent_handshake_pins_the_declared_block(tmp_path):
    """The latent block is host-declared DATA — pinned exactly, so any
    change is a declaration change, never a silent knob."""
    assert latent_utility_decl() == {
        "form": "latent@1",
        "said": ["var", 1],
        "residuals": [
            {"name": "theta_ask", "grid": [0.02, 0.05, 0.1, 0.2, 0.4]},
        ],
        "tau": {"points": [0.5, 1, 2], "weights": [0.5, 0.3, 0.2]},
        "price": "tick-price",
        "gauge": {"zero": "status-quo", "scale": "usd"},
    }
    # the grid floor is SOURCED from the incumbent's declared ask price
    assert latent_utility_decl()["residuals"][0]["grid"][0] == UTILITY["interrupt_cost"]
    # the world block is identical across generations; only utility switches
    table, latent = handshake_decl("table@1"), handshake_decl("latent@1")
    assert latent["world"]["utility"] == latent_utility_decl()
    for key in ("namespace", "guards", "menu", "echo"):
        assert latent["world"][key] == table["world"][key]
    with pytest.raises(ValueError):
        handshake_decl("steps@2")


def test_unknown_utility_form_refused(tmp_path):
    with pytest.raises(ValueError):
        MembraneSession(
            FakeWire([]).client(), str(tmp_path),
            ObservationLog(str(tmp_path / "log.jsonl")),
            logline=lambda _m: None, utility_form="steps@2")


def test_latent_boot_records_ulatents(tmp_path):
    _wire, sess = make_latent_session(tmp_path, [LATENT_HANDSHAKE_OK])
    sess.boot()
    assert sess.engine["ulatents"] == 2
    assert sess.engine["utility_form"] == "latent@1"


def test_latent_decide_sends_features_and_menu_only(tmp_path):
    wire, sess = make_latent_session(
        tmp_path,
        [LATENT_HANDSHAKE_OK,
         {"choice": {"fire": 2, "slots": {}}, "p1": 0.5, "entropy_bits": 3.2,
          "residual_mean": 0.42, "sensitivity": True}],
    )
    sess.boot()
    assert sess.decide({"tool-name": "bash"}, profile={"cost": 9.0}) == "block"
    tick = wire.sent[1]["tick"]
    assert "utility" not in tick          # per-tick tables are a v1 concept
    assert tick["menu"] == [3, 2, 1]      # R1 order, normative
    assert tick["features"]["t"] == 0.0
    assert tick["features"]["tool-name=bash"] == 1.0


def test_latent_decide_is_a_pure_choice_relay(tmp_path):
    """Two replies identical except every observability scalar => the
    identical action; readouts land in last_readouts untouched
    (HOSTS_PLAN 8.12(b): branching on them is host-side forking)."""
    wire, sess = make_latent_session(
        tmp_path,
        [LATENT_HANDSHAKE_OK,
         {"choice": {"fire": 2, "slots": {}}, "p1": 0.9, "entropy_bits": 1.0,
          "residual_mean": 0.05, "sensitivity": False},
         {"choice": {"fire": 2, "slots": {}}, "p1": 0.1, "entropy_bits": 9.0,
          "residual_mean": 0.95, "sensitivity": True}],
    )
    sess.boot()
    a1 = sess.decide({"tool-name": "bash"})
    r1 = dict(sess.last_readouts)
    a2 = sess.decide({"tool-name": "bash"})
    r2 = dict(sess.last_readouts)
    assert a1 == a2 == "block"
    assert r1 == {"p1": 0.9, "entropy_bits": 1.0, "residual_mean": 0.05,
                  "sensitivity": False}
    assert r2 == {"p1": 0.1, "entropy_bits": 9.0, "residual_mean": 0.95,
                  "sensitivity": True}


def test_latent_verdict_double_feeds_same_t(tmp_path):
    """One human verdict => an untagged world-report tick then a
    "verdict" pointer tick, SAME t, the clock advancing once."""
    wire, sess = make_latent_session(
        tmp_path,
        [LATENT_HANDSHAKE_OK,
         {"observed": 1, "loss_bits": 0.4},
         {"observed": 1, "loss_bits": 0.1},
         {"choice": {"fire": 1, "slots": {}}}],
    )
    sess.boot()
    sess.observe({"tool-name": "bash"}, 1)
    world, verdict = wire.sent[1]["tick"], wire.sent[2]["tick"]
    assert "stream" not in world
    assert verdict["stream"] == "verdict"
    assert world["evidence"] == verdict["evidence"] == 1
    assert world["features"]["t"] == verdict["features"]["t"] == 0.0
    assert world["features"] == verdict["features"]
    sess.decide({"tool-name": "bash"})
    assert wire.sent[3]["tick"]["features"]["t"] == 1.0  # advanced ONCE


def test_latent_outcome_tick_tagged_and_deduped(tmp_path):
    wire, sess = make_latent_session(
        tmp_path,
        [LATENT_HANDSHAKE_OK, {"observed": 1, "loss_bits": 0.2}],
    )
    sess.boot()
    sess.observe_outcome("evt_1", {"tool-name": "bash"}, 1)
    tick = wire.sent[1]["tick"]
    assert tick["stream"] == "outcome"
    assert tick["evidence"] == 1
    assert tick["features"]["t"] == 0.0
    assert sess._t == 1
    # same event again: nothing sent (the seen-set spans the session)
    sess.observe_outcome("evt_1", {"tool-name": "bash"}, 0)
    assert len(wire.sent) == 2
    assert sess._t == 1


def test_table_outcome_is_inert(tmp_path):
    """table@1 has no outcome channel (epoch 1): observe_outcome is a
    documented no-op, nothing crosses the wire."""
    wire = FakeWire([HANDSHAKE_OK])
    sess = MembraneSession(
        wire.client(), str(tmp_path),
        ObservationLog(str(tmp_path / "log.jsonl")),
        logline=lambda _m: None)
    sess.boot()
    sess.observe_outcome("evt_1", {"tool-name": "bash"}, 1)
    assert len(wire.sent) == 1  # handshake only
    assert sess._t == 0


def test_latent_warm_boot_uses_observe_counts(tmp_path):
    """The fixed warm corpus collapses: per context one untagged +
    one "verdict" observe_counts line, same t, the clock advancing by
    the context's evidence mass (R-D23 declared segmentation)."""
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / GOVERNANCE["warm_counts_file"]).write_text(json.dumps({
        "features": GOVERNANCE["feature_names"],
        "contexts": [
            {"ctx": ["bash", "project-root", "none", "rep-0", "ident-0", "lt-30s"],
             "n1": 30, "n0": 9},
            {"ctx": ["read", "subdirectory", "none", "rep-1", "ident-0", "lt-2m"],
             "n1": 4, "n0": 0},
        ],
    }))
    wire, sess = make_latent_session(
        tmp_path,
        [LATENT_HANDSHAKE_OK,
         {"observed": 39}, {"observed": 39},
         {"observed": 4}, {"observed": 4}],
        brain_dir=str(brain),
    )
    sess.boot()
    assert len(wire.sent) == 5  # handshake + 2 contexts x 2 roles
    c1_world, c1_verdict = wire.sent[1]["observe_counts"], wire.sent[2]["observe_counts"]
    assert "stream" not in c1_world
    assert c1_verdict["stream"] == "verdict"
    assert c1_world["counts"] == c1_verdict["counts"] == {"1": 30, "0": 9}
    assert c1_world["features"]["t"] == c1_verdict["features"]["t"] == 0.0
    assert c1_world["features"]["tool-name=bash"] == 1.0
    c2_world = wire.sent[3]["observe_counts"]
    assert c2_world["features"]["t"] == 39.0          # advanced by n1+n0
    assert c2_world["counts"] == {"1": 4, "0": 0}
    assert sess._t == 43


def test_latent_boot_replays_log_outcomes(tmp_path):
    """Boot feeds the log's verdict history then its outcome history
    (the declared two-segment order), deduped against live submits."""
    log_path = tmp_path / "log.jsonl"
    log = ObservationLog(str(log_path))
    log.append({"event_type": "tool-proposed", "event_id": "e1",
                "features": {"tool-name": "bash"}})
    log.append({"event_type": "user-responded", "in_response_to": "e1",
                "response": "yes"})
    log.append({"event_type": "outcome", "in_response_to": "e1",
                "source": "grounding", "completed": True, "reverted": False,
                "latency_s": None, "spend_usd": None, "retries": 0,
                "error": None})
    wire = FakeWire([
        LATENT_HANDSHAKE_OK,
        {"observed": 1}, {"observed": 1},   # verdict double-feed
        {"observed": 1},                     # outcome tick
    ])
    sess = MembraneSession(wire.client(), str(tmp_path), log,
                           logline=lambda _m: None, utility_form="latent@1")
    sess.boot()
    assert len(wire.sent) == 4
    assert wire.sent[3]["tick"]["stream"] == "outcome"
    assert wire.sent[3]["tick"]["evidence"] == 1
    # live re-submit of the same event: deduped by the seen-set
    sess.observe_outcome("e1", {"tool-name": "bash"}, 1)
    assert len(wire.sent) == 4


def test_latent_error_reply_raises(tmp_path):
    _wire, sess = make_latent_session(
        tmp_path, [LATENT_HANDSHAKE_OK, {"error": "unknown-stream:vibes"}])
    sess.boot()
    with pytest.raises(MembraneError):
        sess.observe_outcome("e9", {"tool-name": "bash"}, 1)


def test_latent_think_maps_to_fail_open_proceed(tmp_path):
    _wire, sess = make_latent_session(
        tmp_path, [LATENT_HANDSHAKE_OK, {"choice": {"internal": "think"}}])
    sess.boot()
    assert sess.decide({"tool-name": "bash"}) == "proceed"


@pytest.mark.skipif(
    not os.environ.get(MEMBRANE_ENV),
    reason=f"end-to-end path needs {MEMBRANE_ENV} pointing at proplang-govhost",
)
def test_end_to_end_latent_against_real_driver(tmp_path):
    from credence_governor_core.membrane import build_membrane_session

    log = ObservationLog(str(tmp_path / "log.jsonl"))
    sess = build_membrane_session(str(tmp_path), log, logline=lambda _m: None,
                                  utility_form="latent@1")
    try:
        sess.boot()
        assert sess.engine["models"] == 3977
        assert sess.engine["ulatents"] == 2
        # the stated prediction (docs/membrane-shadow.md; the plan's
        # verified central finding): the wire-expressible said subset is
        # action-degenerate, so the latent governor fires block — first-
        # listed among the tied non-charged options — on every tick.
        assert sess.decide({"tool-name": "bash"}) == "block"
        sess.observe({"tool-name": "bash"}, 1)          # verdict round-trip
        sess.observe_outcome("evt_e2e", {"tool-name": "bash"}, 1)
        assert sess.decide({"tool-name": "bash"}) == "block"
    finally:
        sess.client.shutdown()
