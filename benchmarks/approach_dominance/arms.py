# Role: eval
"""Competitor arms — the "other approaches out there" the claim must beat.

Two families:
  * **Routing foils** (ported structure-for-structure from the engine's `baselines.py`,
    which is pure functions over the frozen grid — they touch neither the skin nor any
    engine internal). Each is a profile-agnostic fixed rule or a clairvoyant upper bound,
    standing in for a class of deployed router. `source = "measured"` (they read measured
    correctness/cost off the oracle grid).
  * **Compression wrappers** (new here — each encodes a competitive claim). A compressor
    does NOT route; it takes a base arm and cuts its cost. `source = "modelled"`. The only
    place "Credence pulls compression" appears is the STACKED arm built in `dominance.py`
    (compressor ∘ the measured Credence-routed arm) — measured-routing × modelled-compression.

Every arm maps a question (any object with `.id` and `.category`) to a realised
`(correct: bool, cost: float)` against the SAME frozen grid, so all arms score on
identical ground truth (§3 same-ground-truth invariant).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from synthetic_competitors import SYNTH_COMPRESSOR, tokenshift_cost_mult

Arm = Callable[[object], "tuple[bool, float]"]
Grid = "dict[tuple[int, str], bool]"  # (model_idx, question_id) -> was_correct


@dataclass(frozen=True)
class ArmSpec:
    """An arm + its provenance. `source` drives the per-cell measured/modelled tag (G1);
    `klass` is the competitor class the win/tie/loss map groups by."""
    name: str
    fn: Arm
    source: str   # "measured" | "modelled"
    klass: str    # "routing" | "compression" | "credence" | "stacked"


# ── routing foils (ported from engine baselines.py — pure, no skin) ───────────
def empirical_accuracy(grid, train_ids, questions, n_models, categories):
    """Per-(model, category) train-split accuracy: dict[(m, cat)] -> (acc, n)."""
    ids_by_cat = {
        c: [q.id for q in questions if q.id in train_ids and q.category == c]
        for c in categories
    }
    acc = {}
    for m in range(n_models):
        for c in categories:
            ids = ids_by_cat[c]
            if ids:
                k = sum(1 for qid in ids if grid[(m, qid)])
                acc[(m, c)] = (k / len(ids), len(ids))
            else:
                acc[(m, c)] = (0.5, 0)  # no-data fallback for a non-Bayesian foil
    return acc


def make_always(grid, costs, k: int) -> Arm:
    """Single-model policy: always model k (a cost floor / quality ceiling bound)."""
    return lambda q: (grid[(k, q.id)], costs[k])


def make_argmax_accuracy(grid, costs, acc, categories, n_models) -> Arm:
    """Most accurate model per category (ties → cheaper). Cost-blind."""
    best = {
        c: min(range(n_models), key=lambda m: (-acc[(m, c)][0], costs[m]))
        for c in categories
    }
    return lambda q: (grid[(best[q.category], q.id)], costs[best[q.category]])


def make_best_fixed_table(grid, costs, acc, categories, n_models, profile_rewards) -> Arm:
    """Single category→model table maximising mean welfare across profiles (Wald foil):
    the best a profile-agnostic static router can do — it cannot be the per-profile
    argmax for more than one profile."""
    def mean_welfare(m, c):
        return sum(r * acc[(m, c)][0] - costs[m] for r in profile_rewards) / len(profile_rewards)

    best = {c: max(range(n_models), key=lambda m: mean_welfare(m, c)) for c in categories}
    return lambda q: (grid[(best[q.category], q.id)], costs[best[q.category]])


def make_threshold_router(grid, costs, acc, categories, n_models) -> Arm:
    """RouteLLM-style 2-bin router: cheapest vs most-capable, split at a difficulty cut
    (midpoint of the cheapest model's per-category accuracy range). Binary by construction."""
    cheap = min(range(n_models), key=lambda m: costs[m])
    strong = max(range(n_models), key=lambda m: costs[m])
    cheap_acc = {c: acc[(cheap, c)][0] for c in categories}
    cut = (min(cheap_acc.values()) + max(cheap_acc.values())) / 2.0
    pick = {c: (cheap if cheap_acc[c] >= cut else strong) for c in categories}
    return lambda q: (grid[(pick[q.category], q.id)], costs[pick[q.category]])


def make_oracle_cascade(grid, costs, order) -> Arm:
    """FrugalGPT-style cheapest-first escalation, charged the CUMULATIVE cost of every
    rung tried; clairvoyant (stops at the first actually-correct rung) — an UPPER BOUND
    on any real cascade, which needs a fallible verifier to decide to stop."""
    def arm(q):
        spent = 0.0
        for m in order:
            spent += costs[m]
            if grid[(m, q.id)]:
                return (True, spent)
        return (False, spent)
    return arm


# ── compression wrappers (modelled; the single-lever upper-bound family) ──────
def make_compressor(cost_mult: float, quality_delta: float = 0.0) -> Callable[[Arm], Arm]:
    """Wrap a base arm with idealised compression: cost × cost_mult, correctness preserved.

    `quality_delta` is the fraction of correct answers compression would break; the steelman
    bound is 0.0 (the competitor's own claim — compression preserves correctness, §App-C-4).
    Preserving correctness is the *upper bound* on the class (favourable-to-competitor =
    more correct at lower cost), so we keep the outcome and only discount cost. The param is
    carried for the assertion that we never model it below the competitor's claimed value."""
    def wrap(base: Arm) -> Arm:
        def arm(q):
            correct, cost = base(q)
            return (correct, cost * cost_mult)
        return arm
    return wrap


def synth_compressor() -> Callable[[Arm], Arm]:
    """The §App-A best-plausible compressor (30% cut, zero quality loss)."""
    return make_compressor(SYNTH_COMPRESSOR["cost_mult"], SYNTH_COMPRESSOR["quality_delta"])


def tokenshift_compressor() -> Callable[[Arm], Arm]:
    """TokenShift as a named point inside the compression class (cost_mult ≈ 0.86)."""
    return make_compressor(tokenshift_cost_mult(), 0.0)
