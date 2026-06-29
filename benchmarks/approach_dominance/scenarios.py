# Role: eval
"""Scenario generator (§5.2 — measured-anchored hybrid).

Emits a scenario *set* so "wide range of scenarios" is explicit, not a single grid,
varying routing-headroom, category mix, and difficulty. The measured/modelled line is
policed by three guardrails written into the structure here:

  * **G1 (per-cell tags that propagate).** Each Scenario declares `source`. A cell's final
    source (computed in dominance.py) is measured iff the scenario is measured AND the arm
    is measured; the headline integrates the measured subset only.
  * **G2 (synthetic confined to the headroom axis).** Only `headroom_scenarios()` synthesise
    correctness. `category_mix_scenarios()` and `difficulty_scenarios()` are *subsets of the
    measured grid* — real outcomes, reweighted. Synthesising difficulty/correctness to widen
    coverage would be the drift into synthetic-but-wide and is forbidden here by construction.
  * **G3 (synthetic cells adversarial by construction).** The headroom knob's no-headroom end
    is the worst realistic case for Credence — only the priciest model is ever correct, so
    routing is forced to it and a compressor saves the most. Never a neutral midpoint.

Meta-finding (§App-C-7): on the measured anchor, *no* no-headroom category occurs — every
category has a cheaper-and-correct model somewhere. The no-headroom cell exists ONLY in the
synthetic headroom scenarios; that absence is itself the measured result.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "oracle_grid.json")


@dataclass
class Scenario:
    name: str
    axis: str          # "anchor" | "category-mix" | "difficulty" | "headroom"
    source: str        # "measured" | "modelled" (grid provenance)
    headroom: str      # "real" | "none" | "mild" | "strong"
    model_names: list[str]
    costs: list[float]
    categories: list[str]
    questions: list[SimpleNamespace]
    grid: dict          # (model_idx, qid) -> bool


# ── the measured anchor ───────────────────────────────────────────────────────
def _load_fixture():
    data = json.loads(open(FIXTURE).read())
    model_names, costs = data["models"], data["costs"]
    n = len(model_names)
    grid = {}
    for k, v in data["grid"].items():
        mi, qid = k.split("|", 1)
        grid[(int(mi), qid)] = bool(v)
    # keep only questions every model answered (a complete grid row)
    questions = [
        SimpleNamespace(id=q["id"], category=q["category"], difficulty=q.get("difficulty", "medium"))
        for q in data["questions"]
        if all((mi, q["id"]) in grid for mi in range(n))
    ]
    categories = sorted({q.category for q in questions})
    return model_names, costs, categories, questions, grid


def load_anchor() -> Scenario:
    model_names, costs, categories, questions, grid = _load_fixture()
    return Scenario("anchor", "anchor", "measured", "real",
                    model_names, costs, categories, questions, grid)


def _subset(anchor: Scenario, name: str, axis: str, keep) -> Scenario | None:
    """A MEASURED scenario: the anchor restricted to questions satisfying `keep` (real
    outcomes, reweighted). Returns None if the subset is empty or single-category."""
    qs = [q for q in anchor.questions if keep(q)]
    cats = sorted({q.category for q in qs})
    if len(qs) < 4 or len(cats) < 1:
        return None
    sub_grid = {(m, q.id): anchor.grid[(m, q.id)] for q in qs for m in range(len(anchor.model_names))}
    return Scenario(name, axis, "measured", "real",
                    anchor.model_names, anchor.costs, cats, qs, sub_grid)


def category_mix_scenarios(anchor: Scenario) -> list[Scenario]:
    """Measured resamples reweighting the category mix (real outcomes, narrower mix)."""
    out = []
    for c in anchor.categories:
        s = _subset(anchor, f"mix-{c}-heavy", "category-mix", lambda q, c=c: q.category == c)
        if s is not None:
            out.append(s)
    return out


def difficulty_scenarios(anchor: Scenario) -> list[Scenario]:
    """Measured resamples by difficulty (real outcomes; shift the mass toward hard)."""
    levels = sorted({q.difficulty for q in anchor.questions})
    out = []
    if "hard" in levels:
        out.append(_subset(anchor, "difficulty-hard-shifted", "difficulty",
                           lambda q: q.difficulty in ("medium", "hard")))
    if "easy" in levels:
        out.append(_subset(anchor, "difficulty-easy", "difficulty",
                           lambda q: q.difficulty == "easy"))
    return [s for s in out if s is not None]


# ── the synthetic headroom sweep (modelled; the ONLY synthesis) ───────────────
# Per-category correctness patterns over [cheap, mid, exp]. Each is deterministic and
# homogeneous within a category, so the scenario is split-invariant (no sampling noise) —
# the cleanest demonstration, exactly as the engine's build_toy_oracle.
_HEADROOM_PATTERNS = {
    # no headroom (G3 adversarial): only exp is ever correct ⇒ routing forced to exp,
    # a compressor saves 30% of the priciest model. THE §4 loss cell.
    "none": {"only-exp": [0, 0, 1]},
    # mild: some categories cheap suffices, some need exp (a realistic mixed workload).
    "mild": {"cheap-ok": [1, 1, 1], "only-exp": [0, 0, 1]},
    # strong specialisation: each model is the sole correct one on its category ⇒ routing
    # is essential and Credence has maximal headroom.
    "strong": {"cheap-best": [1, 0, 0], "mid-best": [0, 1, 0], "exp-best": [0, 0, 1]},
}


def headroom_scenarios(anchor: Scenario, per_cat: int = 8) -> list[Scenario]:
    """Synthetic correctness surfaces spanning routing-headroom. Costs reuse the measured
    anchor's dollar ladder so cost comparisons stay on one scale. source = 'modelled'."""
    out = []
    n = len(anchor.model_names)
    for level, patterns in _HEADROOM_PATTERNS.items():
        cats = list(patterns)
        questions, grid = [], {}
        for c in cats:
            for i in range(per_cat):
                q = SimpleNamespace(id=f"{level}-{c}-{i}", category=c, difficulty="synthetic")
                questions.append(q)
                for m in range(n):
                    grid[(m, q.id)] = bool(patterns[c][m])
        out.append(Scenario(f"headroom-{level}", "headroom", "modelled", level,
                            anchor.model_names, anchor.costs, cats, questions, grid))
    return out


def all_scenarios() -> list[Scenario]:
    """The full set: measured anchor + measured resamples + synthetic headroom sweep."""
    anchor = load_anchor()
    return ([anchor]
            + category_mix_scenarios(anchor)
            + difficulty_scenarios(anchor)
            + headroom_scenarios(anchor))
