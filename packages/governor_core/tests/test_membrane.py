"""test_membrane.py — the membrane adapter's hermetic tests (HOSTS_PLAN
2.7). The transport is injected (no process, no engine): these pin the
adapter's pure conventions — the one-hot projection, the R1-ruled menu
order, the utility table, the t-convention, the reply mapping, warm
flattening — against the recorded register. The end-to-end path runs
only when CREDENCE_MEMBRANE_COMMAND points at a real driver binary."""

import json
import os

import pytest

from credence_governor_core.config import GOVERNANCE, UTILITY
from credence_governor_core.log import ObservationLog
from credence_governor_core.membrane import (
    AFFORDANCES,
    MEMBRANE_ENV,
    MENU_IDS,
    MembraneClient,
    MembraneError,
    MembraneSession,
    flatten_warm_counts,
    handshake_decl,
    indicator_names,
    onehot,
    utility_rows,
)


class FakeWire:
    """Scripted transport: records every request line, replays queued
    replies (dicts), so the adapter is tested without any process."""

    def __init__(self, replies):
        self.sent: list[dict] = []
        self.replies = list(replies)

    def client(self) -> MembraneClient:
        def write_line(s: str) -> None:
            self.sent.append(json.loads(s))

        def read_line() -> str:
            return json.dumps(self.replies.pop(0))

        return MembraneClient(write_line, read_line)


def make_session(tmp_path, replies, brain_dir=None):
    wire = FakeWire(replies)
    log = ObservationLog(str(tmp_path / "log.jsonl"))
    sess = MembraneSession(
        wire.client(),
        brain_dir or str(tmp_path),  # no counts file => no warm replay
        log,
        logline=lambda _m: None,
    )
    return wire, sess


HANDSHAKE_OK = {"ok": True, "proto": 1, "models": 3977, "namespace_bits": 5.321928094887363}


def test_indicators_are_the_39_declared_values():
    inds = indicator_names()
    assert len(inds) == 39
    assert "tool-name=bash" in inds
    assert "time-since-last-user-message=gt-10m" in inds


def test_onehot_projects_out_harm_keys_and_unknown_values():
    f = {
        "tool-name": "bash",
        "working-directory-relative": "project-root",
        "coding-action-class": "exec",          # harm key: projected out
        "recent-repetition-count": "rep-99",    # unknown value: dormant
    }
    enc = onehot(f)
    assert enc == {"tool-name=bash": 1.0, "working-directory-relative=project-root": 1.0}


def test_menu_order_is_the_r1_ruling():
    assert AFFORDANCES == [("ask", 3), ("block", 2), ("proceed", 1)]
    assert MENU_IDS == [3, 2, 1]


def test_utility_rows_default_and_profile():
    rows = {tuple(sorted(r)): r for r in utility_rows()}
    by_key = {r.get("fire", r.get("internal")): r["u"] for r in utility_rows()}
    c, lam, q = UTILITY["cost"], UTILITY["aversion"], UTILITY["interrupt_cost"]
    assert by_key[3] == [-q, -q]
    assert by_key[2] == [0.0, -lam * c]
    assert by_key[1] == [-c, 0.0]
    assert by_key["think"][0] == by_key["think"][1] < -(c + lam * c)  # dominated sentinel
    assert rows  # rows well-formed
    prof = {"cost": 2.0, "aversion": 3.0, "interrupt_cost": 0.5}
    by_key2 = {r.get("fire", r.get("internal")): r["u"] for r in utility_rows(prof)}
    assert by_key2[1] == [-2.0, 0.0]
    assert by_key2[2] == [0.0, -6.0]
    assert by_key2[3] == [-0.5, -0.5]


def test_handshake_declares_the_world():
    d = handshake_decl()
    w = d["world"]
    assert d["membrane"] == 1
    assert len(w["namespace"]) == 40 and w["namespace"][0] == "t"
    assert len(w["guards"]) == 39
    assert all(g["grid"] == [0.5] for g in w["guards"])
    assert [m["id"] for m in w["menu"]] == [3, 2, 1]
    assert all(m["slots"] == [] for m in w["menu"])
    assert w["echo"] == {
        "last_action": False, "tick": False, "ticks_spent_thinking": False}


def test_boot_decide_observe_flow(tmp_path):
    wire, sess = make_session(
        tmp_path,
        [
            HANDSHAKE_OK,
            {"choice": {"fire": 3, "slots": {}}, "p1": 0.5, "entropy_bits": 3.2},
            {"observed": 1, "loss_bits": 0.4},
            {"choice": {"fire": 1, "slots": {}}, "p1": 0.9, "entropy_bits": 2.0},
        ],
    )
    sess.boot()
    assert sess.engine["models"] == 3977

    action = sess.decide({"tool-name": "bash"})
    assert action == "ask"
    tick = wire.sent[1]["tick"]
    assert tick["menu"] == [3, 2, 1]                      # R1 order, normative
    assert tick["features"]["t"] == 0.0                   # evidence clock at 0
    assert tick["features"]["tool-name=bash"] == 1.0
    assert tick["utility"]["form"] == "table@1"           # per-tick profile table

    sess.observe({"tool-name": "bash"}, 1)
    ev = wire.sent[2]["tick"]
    assert ev["evidence"] == 1 and ev["features"]["t"] == 0.0
    assert "menu" not in ev                               # evidence tick, no menu

    assert sess.decide({"tool-name": "bash"}) == "proceed"
    assert wire.sent[3]["tick"]["features"]["t"] == 1.0   # clock advanced


def test_think_reply_maps_to_fail_open_proceed(tmp_path):
    wire, sess = make_session(
        tmp_path,
        [HANDSHAKE_OK, {"choice": {"internal": "think"}, "p1": 0.5, "entropy_bits": 1.0}],
    )
    sess.boot()
    assert sess.decide({"tool-name": "bash"}) == "proceed"
    assert wire.sent  # transport exercised


def test_error_reply_raises(tmp_path):
    _wire, sess = make_session(
        tmp_path, [HANDSHAKE_OK, {"error": "impossible-evidence"}])
    sess.boot()
    with pytest.raises(MembraneError):
        sess.observe({"tool-name": "bash"}, 7)


def test_harm_and_routing_are_inert(tmp_path):
    _wire, sess = make_session(tmp_path, [HANDSHAKE_OK])
    sess.boot()
    assert sess.observe_harm({"coding-action-class": "exec"}, 1) is None
    assert sess.route({"prompt-length": "short"}) is None
    assert sess.supports("structure_expect") is False


def test_flatten_warm_counts_order_and_mismatch():
    counts = {
        "features": GOVERNANCE["feature_names"],
        "contexts": [
            {"ctx": ["bash", "project-root", "none", "rep-0", "ident-0", "lt-30s"],
             "n1": 2, "n0": 1},
        ],
    }
    ticks = list(flatten_warm_counts(counts))
    assert [obs for _f, obs in ticks] == [1, 1, 0]
    assert ticks[0][0]["tool-name"] == "bash"
    with pytest.raises(ValueError):
        list(flatten_warm_counts({"features": ["wrong"], "contexts": []}))


def test_warm_replay_feeds_evidence_ticks(tmp_path):
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / GOVERNANCE["warm_counts_file"]).write_text(json.dumps({
        "features": GOVERNANCE["feature_names"],
        "contexts": [
            {"ctx": ["bash", "project-root", "none", "rep-0", "ident-0", "lt-30s"],
             "n1": 1, "n0": 1},
        ],
    }))
    wire, sess = make_session(
        tmp_path,
        [HANDSHAKE_OK,
         {"observed": 1, "loss_bits": 0.1},
         {"observed": 0, "loss_bits": 0.2}],
        brain_dir=str(brain),
    )
    sess.boot()
    assert len(wire.sent) == 3                       # handshake + 2 warm ticks
    assert wire.sent[1]["tick"]["evidence"] == 1
    assert wire.sent[2]["tick"]["evidence"] == 0
    assert sess._t == 2                              # the clock counted them


@pytest.mark.skipif(
    not os.environ.get(MEMBRANE_ENV),
    reason=f"end-to-end path needs {MEMBRANE_ENV} pointing at proplang-govhost",
)
def test_end_to_end_against_real_driver(tmp_path):
    os.environ.setdefault("CREDENCE_MEMBRANE_WARM_CAP", "0")
    from credence_governor_core.membrane import build_membrane_session

    log = ObservationLog(str(tmp_path / "log.jsonl"))
    sess = build_membrane_session(str(tmp_path), log, logline=lambda _m: None)
    try:
        sess.boot()
        assert sess.engine["models"] == 3977
        a = sess.decide({"tool-name": "bash"})
        assert a in ("proceed", "block", "ask")
        sess.observe({"tool-name": "bash"}, 1)
        a2 = sess.decide({"tool-name": "bash"})
        assert a2 in ("proceed", "block", "ask")
    finally:
        sess.client.shutdown()
