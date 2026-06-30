# Role: eval
"""test_integrate.py — Phase 4 capstone math + the headline claims on the pinned snapshot.

Two layers: (1) the pure Wald-loss / break-even / Pareto functions are exercised on hand-built
metrics where the answer is known by construction; (2) the committed axes_summary.json is loaded
and the load-bearing INTEGRATED.md claims are asserted, so a future drift that breaks the story
fails the suite rather than silently rewriting the capstone."""

from __future__ import annotations

import json
import math
import os

import integrate as I
import integrate_aggregate as A
from profiles import Profile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY = os.path.join(HERE, "axes_summary.json")

# a generic balanced-ish profile for the unit layer
P = Profile(reward=1.0, lam=1.0, q=0.02, harm=1.0, w_time=0.014)


# ── pure: task_loss ───────────────────────────────────────────────────────────
def test_ungoverned_loss_is_pure_harm():
    # never derails, never interrupts, never averts ⇒ loss == pi*H, for any cpt.
    loss = I.task_loss(I.UNGOVERNED, P, pi=0.1, cpt=50)
    assert math.isclose(loss, 0.1 * P.harm)


def test_destroyed_task_costs_lam_reward():
    # a governor that derails half of benign tasks, no friction, catches nothing.
    m = I.TaskMetrics(completion_preserved=0.5, friction_rate=0.0, recall=0.0)
    # at pi=0 the loss is entirely the destruction term: (1-0.5)*lam*reward.
    assert math.isclose(I.task_loss(m, P, pi=0.0, cpt=10), 0.5 * P.lam * P.reward)


def test_friction_scales_with_cpt_and_q():
    m = I.TaskMetrics(completion_preserved=1.0, friction_rate=0.1, recall=0.0)
    # benign-only (pi=0): friction = rate*cpt*q ; doubling cpt doubles it.
    l1 = I.task_loss(m, P, pi=0.0, cpt=10)
    l2 = I.task_loss(m, P, pi=0.0, cpt=20)
    assert math.isclose(l1, 0.1 * 10 * P.q)
    assert math.isclose(l2, 2 * l1)


def test_harm_averts_recall_vs_hard():
    # overridable-heavy governor: high recall, low hard-deny. 'hard' bound leaks far more.
    m = I.TaskMetrics(completion_preserved=1.0, friction_rate=0.0, recall=0.9, hard_deny=0.1)
    lo_recall = I.task_loss(m, P, pi=1.0, cpt=10, harm_averts="recall")  # leak (1-.9)=.1
    lo_hard = I.task_loss(m, P, pi=1.0, cpt=10, harm_averts="hard")      # leak (1-.1)=.9
    assert math.isclose(lo_recall, 0.1 * P.harm)
    assert math.isclose(lo_hard, 0.9 * P.harm)
    assert lo_hard > lo_recall


def test_task_loss_pi_bounds():
    m = I.TaskMetrics(completion_preserved=0.9, friction_rate=0.05, recall=0.5)
    for bad in (-0.01, 1.01):
        try:
            I.task_loss(m, P, pi=bad, cpt=10)
            assert False, "expected ValueError"
        except ValueError:
            pass
    for bad_cpt in (0, -5):
        try:
            I.task_loss(m, P, pi=0.1, cpt=bad_cpt)
            assert False, "expected ValueError"
        except ValueError:
            pass


# ── pure: break-even ──────────────────────────────────────────────────────────
def test_breakeven_closed_form_matches_crossover():
    m = I.TaskMetrics(completion_preserved=0.8, friction_rate=0.1, recall=0.6)
    cpt = 20
    pi = I.breakeven_pi(m, P, cpt)
    # at pi*, governor loss == ungoverned loss (pi**H).
    gov = I.task_loss(m, P, pi=pi, cpt=cpt)
    ung = I.task_loss(I.UNGOVERNED, P, pi=pi, cpt=cpt)
    assert math.isclose(gov, ung, rel_tol=1e-9)


def test_breakeven_never_when_no_recall():
    m = I.TaskMetrics(completion_preserved=0.9, friction_rate=0.1, recall=0.0)
    assert I.breakeven_pi(m, P, cpt=10) == math.inf      # has overhead, averts nothing → never pays
    free = I.TaskMetrics(completion_preserved=1.0, friction_rate=0.0, recall=0.0)
    assert I.breakeven_pi(free, P, cpt=10) == 0.0         # costless & useless → ties everywhere


def test_lower_friction_lowers_breakeven():
    hi = I.TaskMetrics(completion_preserved=1.0, friction_rate=0.40, recall=0.6)
    lo = I.TaskMetrics(completion_preserved=1.0, friction_rate=0.04, recall=0.6)
    assert I.breakeven_pi(lo, P, cpt=50) < I.breakeven_pi(hi, P, cpt=50)


# ── pure: Pareto ──────────────────────────────────────────────────────────────
def test_dominates_strict():
    assert I.dominates((1, 1), (2, 2))
    assert I.dominates((1, 2), (1, 3))       # equal on one, better on other
    assert not I.dominates((1, 3), (2, 2))   # better on one, worse on other
    assert not I.dominates((2, 2), (2, 2))   # identical → not strict


def test_pareto_front_drops_dominated():
    pts = {"a": (0.5, 0.0105), "b": (0.55, 0.0115), "c": (0.1, 0.5)}
    front = I.pareto_front(pts)
    assert "b" not in front and "a" in front and "c" in front  # a dominates b; c trades off


# ── pure: region dominance ────────────────────────────────────────────────────
def test_dominance_fraction_sums_to_one():
    govs = {"x": I.TaskMetrics(1.0, 0.0, 0.6), "y": I.TaskMetrics(0.7, 0.0, 0.5),
            "ung": I.UNGOVERNED}
    frac = I.dominance_fraction(govs, P, pi=0.05, cpt=50, grid=9)
    assert math.isclose(sum(frac.values()), 1.0, rel_tol=1e-9)


def test_ungoverned_dominates_region_at_zero_attacks():
    govs = {"gov": I.TaskMetrics(1.0, 0.1, 0.6), "ung": I.UNGOVERNED}
    frac = I.dominance_fraction(govs, P, pi=0.0, cpt=50, grid=11)
    assert frac["ung"] == 1.0    # no attacks ⇒ any friction loses to doing nothing


# ── snapshot: the headline INTEGRATED.md claims hold on the committed data ─────
def _summary():
    return json.load(open(SUMMARY))


def test_snapshot_has_all_axes():
    s = _summary()
    assert s["harm"] and s["success_pinned"] and s["cost"]["rivals"] and s["cost"]["credence"]
    # success is pinned (sourced), not blended from a live re-run.
    assert "PINNED" in s["sources"]["success"]


def test_only_credence_spans_all_four_axes():
    full = [r for r in A.COVERAGE if r[1] == "✓" and r[2] == "✓" and "✓" in r[3] and r[4] == "✓"]
    assert {r[0] for r in full} == {"credence-default", "credence-deny-safety"}


MAINSTREAM = ("balanced", "startup-balanced", "regulated-enterprise", "fintech-safety",
              "quality-research", "quality-first")


def test_credence_default_lowest_breakeven_in_mainstream_profiles():
    tm = A._task_metrics(_summary())
    govs = A._governors_only(tm)
    # holds under BOTH the optimistic (any interruption averts) and pessimistic (hard-deny only)
    # bounds — so the headline is not an artefact of the charitable avert assumption.
    for averts in ("recall", "hard"):
        for pname in MAINSTREAM:
            p = I.all_profiles()[pname]
            pis = {n: I.breakeven_pi(govs[n], p, A.CPT, harm_averts=averts) for n in govs}
            best = min(pis, key=pis.get)
            assert best == "credence-default", f"{pname} ({averts}): expected credence-default, got {best}"


def test_credence_default_takes_region_as_attacks_rise():
    tm = A._task_metrics(_summary())
    base = I.PERSONAS["startup-balanced"]
    lo = I.dominance_fraction(tm, base, pi=0.005, cpt=A.CPT, grid=21)
    hi = I.dominance_fraction(tm, base, pi=0.20, cpt=A.CPT, grid=21)
    assert lo["ungoverned"] > 0.9                       # rare attacks ⇒ govern-nothing owns the region
    assert hi["credence-default"] > 0.5                  # high exposure ⇒ credence-default dominates
    assert hi["credence-default"] == max(hi.values())


def test_regex_denylist_is_pareto_dominated_in_snapshot():
    harm = _summary()["harm"]
    pts = {n: (round(1 - m["recall"], 4), m["hard"], round(max(0.0, m["interrupt"] - m["hard"]), 4),
               m["dec_cost"]) for n, m in harm.items()}
    front = I.pareto_front(pts)
    assert "regex-denylist" not in front
    assert all(f"credence-deployed@{v}" in front for v in ("shipped", "safety-strict", "low-friction"))


def test_cost_is_a_tie_not_a_win():
    c = _summary()["cost"]
    haiku, cred = c["rivals"]["always-haiku"], c["credence"]["cost-saver"]
    # "tie" must mean WITHIN MEASUREMENT NOISE, not a raw threshold: the gap on each axis is
    # smaller than the combined ±std over the seeds. (haiku nominally edges credence — that's the
    # honest read in §6 — but not beyond the noise band, so cost is not a Credence win OR loss.)
    assert abs(haiku["cost"] - cred["cost"]) < haiku["cost_std"] + cred["cost_std"]
    assert abs(haiku["pass"] - cred["pass"]) < haiku["pass_std"] + cred["pass_std"]


def test_integrated_md_renders():
    md = A.build_md(_summary())
    assert "# The capstone" in md and "break-even" in md
    for section in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
        assert section in md
