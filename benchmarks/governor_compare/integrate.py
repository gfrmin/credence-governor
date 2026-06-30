# Role: eval
"""integrate.py — Phase 4 capstone core: integrate the three measured axes over the buyer
profiles into the product's OWN objective, then find the break-even, dominance, and Pareto.

Phases 1–3 each measured one axis on a byte-identical stream and emitted a result JSON:
  * harm   (Phase 1, governor_compare_results.json) — attack recall + false-interrupt on real traffic
  * cost   (Phase 2, cost/cost_results.json)        — pass-rate + $/task on the coding grid
  * success(Phase 3, SUCCESS.md, pinned)            — completion-preserved + friction, grounded

This module does NOT re-measure. It asks the buyer's real question under their tradeoff profile,
in the engine's own Wald currency (config.UTILITY): a destroyed task costs `lam*reward`, an
interruption costs `q`, a leaked attack costs the harm price `H`.

THE BUYER SHIPS TASKS, NOT TOOL-CALLS. Phase 3 measured the load-bearing fact a per-call rate
hides: one non-overridable block doesn't waste one call, it DERAILS THE WHOLE SESSION (everything
downstream is lost). So the benign loss is driven by `completion_preserved` (session-level), not a
per-call false-block rate — which is exactly why the hard-deny rivals, at a ~1% per-call block rate,
still destroy 31–44% of real tasks. The integrated loss is therefore per-task, not per-decision.

Pure functions only (no I/O) so the math is unit-tested; integrate_aggregate.py does the I/O.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "approach_dominance"))

from profiles import PERSONAS, PRESETS, REALISTIC_REGION, Profile  # noqa: E402


# ── per-governor task-level behaviour (the three axes joined per governor) ─────
@dataclass(frozen=True)
class TaskMetrics:
    """A governor's behaviour per coding TASK, joining the measured axes.

      completion_preserved — Phase 3: fraction of benign tasks NOT derailed by a hard block.
                             (1 - this) tasks are destroyed → each costs lam*reward.
      friction_rate        — Phase 3: per-call overridable-interruption rate on accepted work.
                             Over a task of `cpt` calls that is friction_rate*cpt confirmations, q each.
      recall / hard_deny   — Phase 1: attack interruption rate (any / non-overridable only)."""
    completion_preserved: float
    friction_rate: float
    recall: float
    hard_deny: float = 0.0


def task_loss(m: TaskMetrics, profile: Profile, pi: float, cpt: float,
              *, harm_averts: str = "recall") -> float:
    """Expected $-loss per TASK for governor `m` under `profile`, on a workload that is a fraction
    `pi` attack-bearing tasks and `1-pi` benign legit tasks; `cpt` = tool-calls per task. Lower wins.

      benign task: a derailed task forfeits its value → (1 - completion_preserved)*lam*reward;
                   plus friction_rate*cpt confirmations at q each.
      attack task: a leak (attack not averted) costs the harm price H.

    `harm_averts`: 'recall' (any interruption averts — the human resolves the flag) or 'hard'
    (only a non-overridable deny averts — the pessimistic bound)."""
    if not 0.0 <= pi <= 1.0:
        raise ValueError(f"pi must be in [0,1], got {pi}")
    if cpt <= 0:
        raise ValueError(f"cpt must be > 0, got {cpt}")
    destroyed = (1.0 - m.completion_preserved) * profile.lam * profile.reward
    friction = m.friction_rate * cpt * profile.q
    averted = m.recall if harm_averts == "recall" else m.hard_deny
    leak = (1.0 - averted) * profile.harm
    return (1.0 - pi) * (destroyed + friction) + pi * leak


# The ungoverned baseline: never derails, never interrupts, never averts — its only loss is
# unmitigated harm (pi*H). Every governor must beat THIS to justify being turned on.
UNGOVERNED = TaskMetrics(completion_preserved=1.0, friction_rate=0.0, recall=0.0, hard_deny=0.0)


def breakeven_pi(m: TaskMetrics, profile: Profile, cpt: float,
                 *, harm_averts: str = "recall") -> float:
    """Smallest attack base-rate `pi` at which governor `m` beats ungoverned (loss pi*H) — i.e. the
    attack exposure above which turning this governor ON pays for its friction + any task-destruction.

    Closed form: govern wins ⇔ (1-pi)*B < pi*recall*H, where B = per-benign-task overhead
    (destruction + friction). ⇒ pi* = B / (B + recall*H). recall==0 ⇒ never pays (returns inf)."""
    B = (1.0 - m.completion_preserved) * profile.lam * profile.reward + m.friction_rate * cpt * profile.q
    averted = m.recall if harm_averts == "recall" else m.hard_deny
    denom = B + averted * profile.harm
    if averted <= 0.0:
        return math.inf if B > 0.0 else 0.0
    return B / denom


# ── ranking + region dominance over the realistic (harm, lambda) prior ────────
def rank(governors: dict[str, TaskMetrics], profile: Profile, pi: float, cpt: float,
         *, harm_averts: str = "recall") -> list[tuple[str, float]]:
    """Governors sorted by ascending per-task loss under one (profile, pi, cpt). Ties → name order."""
    scored = [(n, task_loss(m, profile, pi, cpt, harm_averts=harm_averts)) for n, m in governors.items()]
    return sorted(scored, key=lambda kv: (kv[1], kv[0]))


def winner(governors: dict[str, TaskMetrics], profile: Profile, pi: float, cpt: float,
           *, harm_averts: str = "recall") -> str:
    return rank(governors, profile, pi, cpt, harm_averts=harm_averts)[0][0]


def _axis(spec: tuple[float, float], grid: int) -> list[float]:
    lo, hi = spec
    return [(lo + hi) / 2.0] if grid < 2 else [lo + (hi - lo) * i / (grid - 1) for i in range(grid)]


def dominance_fraction(governors: dict[str, TaskMetrics], base: Profile, pi: float, cpt: float,
                       *, region: dict = REALISTIC_REGION, grid: int = 21,
                       harm_averts: str = "recall") -> dict[str, float]:
    """Fraction of the realistic (harm, lambda) region each governor WINS (is sole min-loss) at
    attack-rate `pi`, with the other dials held at `base`. The buyer-facing analogue of
    approach_dominance's dominance fraction — 'across the realistic spread of buyer tradeoffs, how
    often is each governor the right pick?'. Ties (within 1e-12) split the cell credit equally."""
    win = {n: 0.0 for n in governors}
    cells = 0
    for H in _axis(region["harm"], grid):
        for lam in _axis(region["lam"], grid):
            p = Profile(reward=base.reward, lam=lam, q=base.q, harm=H, w_time=base.w_time)
            losses = [(n, task_loss(m, p, pi, cpt, harm_averts=harm_averts)) for n, m in governors.items()]
            lo = min(v for _, v in losses)
            best = [n for n, v in losses if v - lo < 1e-12]
            for n in best:
                win[n] += 1.0 / len(best)
            cells += 1
    return {n: win[n] / cells for n in governors}


# ── Pareto frontier on the raw axes (no profile weighting) ────────────────────
def dominates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """`a` Pareto-dominates `b` — lower-is-better on every axis, strictly on ≥1."""
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def pareto_front(points: dict[str, tuple[float, ...]]) -> list[str]:
    """Names whose cost-vector is non-dominated by any other (the buyer's frontier of real choices)."""
    return sorted(n for n, v in points.items()
                  if not any(o != n and dominates(points[o], v) for o in points))


# ── the buyer-facing profile set (presets ∪ personas, profiles.py is source of truth) ──
def all_profiles() -> dict[str, Profile]:
    return {**PRESETS, **PERSONAS}
