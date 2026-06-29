# Role: eval
"""Integrity/structure assertions (§3). These assert the bench is SOUND, not that Credence
WINS — dominance is a finding, not an assertion. The pure tests run with no engine; the
JSON tests validate the artifacts when a run has produced them (skipped otherwise)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import arms as A
import routing_belief as RB
import scenarios as SC
from dominance import _verdict
from synthetic_competitors import SYNTH_COMPRESSOR, TOKENSHIFT, tokenshift_cost_mult

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _toy():
    qs = [SimpleNamespace(id=f"q{i}", category="c", difficulty="medium") for i in range(4)]
    grid = {(m, q.id): (m == 2) for q in qs for m in range(3)}  # only model 2 correct (no headroom)
    return qs, grid, [0.001, 0.005, 0.02]


# ── upper-bound discipline (§3): synthetic competitors at the favourable bound ──
def test_synthetic_params_at_favourable_bound():
    assert 0.0 < SYNTH_COMPRESSOR["cost_mult"] <= 1.0      # a cut, never a markup
    assert SYNTH_COMPRESSOR["quality_delta"] == 0.0         # zero quality loss = the steelman
    assert TOKENSHIFT["quality_delta"] == 0.0
    assert 0.0 < tokenshift_cost_mult() <= 1.0


def test_compressor_cuts_cost_preserves_correctness():
    qs, grid, costs = _toy()
    base = A.make_always(grid, costs, 2)
    comp = A.synth_compressor()(base)
    for q in qs:
        bc, bk = base(q)
        cc, ck = comp(q)
        assert cc == bc                                    # correctness preserved (upper bound)
        assert ck == pytest.approx(bk * SYNTH_COMPRESSOR["cost_mult"])


# ── same ground truth + arm contract (§3) ──
def test_every_arm_maps_to_correct_cost_pair():
    qs, grid, costs = _toy()
    acc = A.empirical_accuracy(grid, {q.id for q in qs}, qs, 3, ["c"])
    armset = [
        A.make_always(grid, costs, 0),
        A.make_argmax_accuracy(grid, costs, acc, ["c"], 3),
        A.make_best_fixed_table(grid, costs, acc, ["c"], 3, [1.0]),
        A.make_threshold_router(grid, costs, acc, ["c"], 3),
        A.make_oracle_cascade(grid, costs, [0, 1, 2]),
    ]
    for arm in armset:
        for q in qs:
            correct, cost = arm(q)
            assert isinstance(correct, bool) and isinstance(cost, float) and cost >= 0.0


# ── verdicts are structural, no magic threshold (§3) ──
def test_verdict_is_structural():
    assert _verdict(10.0, 1.0) == "win"
    assert _verdict(-10.0, 1.0) == "loss"
    assert _verdict(0.0, 1.0) == "tie"
    # tie band scales with magnitude, not a hardcoded constant
    assert _verdict(0.001, 1000.0) == "tie"


# ── G2: synthesis is confined to the headroom axis ──
def test_only_headroom_scenarios_are_modelled():
    for sc in SC.all_scenarios():
        if sc.axis == "headroom":
            assert sc.source == "modelled"
        else:
            assert sc.source == "measured", f"{sc.name} ({sc.axis}) must stay measured (G2)"


def test_headroom_none_is_the_adversarial_no_headroom_cell():
    none = next(s for s in SC.all_scenarios() if s.name == "headroom-none")
    n = len(none.model_names)
    priciest = max(range(n), key=lambda m: none.costs[m])
    # G3: only the priciest model is ever correct (worst case for Credence: routing forced, max compression gain)
    for q in none.questions:
        assert none.grid[(priciest, q.id)] is True
        assert all(none.grid[(m, q.id)] is False for m in range(n) if m != priciest)


# ── belief structure the governor reproduces by calling skin primitives ──
def test_preference_shape_is_functional_per_action():
    pref = RB._preference(3, 2, [1.0, 0.0], [0.001, 0.005, 0.02], reward=1.0)
    assert pref["type"] == "functional_per_action"
    assert set(pref["actions"]) == {"0", "1", "2"}
    a0 = pref["actions"]["0"]
    assert a0["type"] == "linear_combination" and a0["offset"] == -0.001
    assert a0["terms"][0][1]["type"] == "nested_projection"


# ── artifact JSON integrity (§3) — run only when a measured run has produced them ──
def _maybe(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        pytest.skip(f"{name} not present (run the cadence first)")
    return json.load(open(p))


def test_routing_results_every_cell_tagged_and_headline_measured():
    r = _maybe("routing_results.json")
    for c in r["cells"]:
        assert c["cell_source"] in ("measured", "modelled")        # no untagged cell
        assert c["verdict"] in ("win", "tie", "loss")
    h = r["headline"]
    assert h["source"] == "measured" and h["measured_cell_count"] > 0   # §7 headline-is-measured
    # the headline integrates ONLY measured cells
    measured = [c for c in r["cells"] if c["cell_source"] == "measured" and c["competitor_class"] == "routing"]
    assert h["measured_cell_count"] == len(measured)


def test_every_loss_carries_a_cause():
    t = _maybe("loss_triage.json")
    assert t["summary"]["n_triaged"] == t["summary"]["n_losses"]       # no untriaged loss
    for row in t["triaged"]:
        assert row["cause"] and row.get("evidence")


def test_harm_strict_win_on_allowed_channel():
    hm = _maybe("harm_results.json")
    assert hm["verdict_strict_win"] is True
    assert hm["detectors"]["credence"]["recall"]["harm_recall"] >= hm["detectors"]["static_policy"]["recall"]["harm_recall"]
