"""test_bench.py — score_engine on hand-built rows, π* closed form,
clears_bar gating, ORACLE/UNGOVERNED calibration ordering."""

import math

import pytest

from credence_governor_core.config import UTILITY

from bench import clears_bar, oracle_decisions, score_engine
from join import join


def _rows(spec):
    """spec: list of (eid, action, outcome_fields|None). Returns BenchRecords."""
    records = []
    for eid, action, outcome_fields in spec:
        records.append({"event_type": "tool-proposed", "event_id": eid,
                        "features": {"tool-name": "bash"}})
        records.append({"event_type": "decision", "in_response_to": eid,
                        "action": action})
        if outcome_fields is not None:
            base = {"event_type": "outcome", "in_response_to": eid,
                    "source": "grounding", "completed": None, "latency_s": None,
                    "spend_usd": None, "reverted": None, "retries": None,
                    "error": None}
            base.update(outcome_fields)
            records.append(base)
    rows, _ = join(records)
    return rows


SPEC = [
    ("e0", "block", {"completed": True}),     # false block: λc = 0.5
    ("e1", "block", {"reverted": True}),      # justified block: 0
    ("e2", "proceed", {"completed": True}),   # good proceed: 0
    ("e3", "proceed", {"reverted": True}),    # missed waste: c = 0.5
    ("e4", "ask", {"completed": True}),       # ask on wanted: q = 0.02
    ("e5", "proceed", {}),                    # ambiguous: bounds only
]


def test_score_engine_known_mean():
    rows = _rows(SPEC)
    s = score_engine(rows, {r.event_id: r.action for r in rows})
    assert s.n_scoreable == 6 and s.n_decisive == 5
    assert s.mean_loss == pytest.approx((0.5 + 0 + 0 + 0.5 + 0.02) / 5)
    # bounds population adds the ambiguous proceed (0 or c)
    lo, hi = s.mean_loss_bounds
    assert lo == pytest.approx(1.02 / 6) and hi == pytest.approx(1.52 / 6)
    assert s.n_bounded == 6
    assert s.fbr_by_category["waste"]["fbr"] == pytest.approx(1 / 3)
    assert s.ask_rate_on_accepted == pytest.approx(1 / 3)
    assert s.catch_on_reverted == pytest.approx(1 / 2)
    assert s.measured_pi == pytest.approx(2 / 5)


def test_breakeven_closed_form():
    rows = _rows(SPEC)
    s = score_engine(rows, {r.event_id: r.action for r in rows})
    c, lam, q = UTILITY["cost"], UTILITY["aversion"], UTILITY["interrupt_cost"]
    B = s.fbr_by_category["waste"]["fbr"] * lam * c + s.ask_rate_on_accepted * q
    assert s.breakeven_pi == pytest.approx(B / (B + s.catch_on_reverted * c))
    # catch 0 with friction => never pays (inf)
    s0 = score_engine(rows, {r.event_id: "block" if r.outcome.label == "accepted"
                             else "proceed" for r in rows})
    assert s0.catch_on_reverted == 0.0 and math.isinf(s0.breakeven_pi)


def test_oracle_and_ungoverned_calibration():
    rows = _rows(SPEC)
    incumbent = score_engine(rows, {r.event_id: r.action for r in rows})
    oracle = score_engine(rows, oracle_decisions(rows))
    ungoverned = score_engine(rows, {r.event_id: "proceed" for r in rows})
    assert oracle.mean_loss == 0.0
    assert ungoverned.mean_loss == pytest.approx(2 * 0.5 / 5)  # π̂·c over decisive
    assert oracle.mean_loss <= ungoverned.mean_loss <= incumbent.mean_loss


def test_clears_bar_shape():
    rows = _rows(SPEC)
    s = score_engine(rows, {r.event_id: r.action for r in rows})
    # no declared bar -> None; declared bar with n_min met -> pass/fail
    assert clears_bar(s, {}, n_min=1) == {"waste": None}
    assert clears_bar(s, {"waste": {"fbr_bar": 0.5}}, n_min=1) == {"waste": True}
    assert clears_bar(s, {"waste": {"fbr_bar": 0.1}}, n_min=1) == {"waste": False}
    # insufficient evidence gates to None even with a declared bar
    assert clears_bar(s, {"waste": {"fbr_bar": 0.5}}, n_min=100) == {"waste": None}


def test_intersection_scoring_ignores_unknown_events():
    rows = _rows(SPEC)
    partial = {"e0": "proceed", "e3": "block", "zzz": "block"}
    s = score_engine(rows, partial)
    assert s.n_scoreable == 2           # e0 + e3; zzz has no corpus row
    assert s.mean_loss == pytest.approx(0.0)  # proceed/accepted + block/reverted
