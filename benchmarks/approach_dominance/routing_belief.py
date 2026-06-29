# Role: eval
"""Skin-backed Beta-Bernoulli routing belief — the governor's port of the engine's
`routing_state.py`, reproduced by CALLING skin primitives, never by importing
`credence_router` internals (the repo-boundary thesis, §1/§2).

θ_{model,category} = P(model answers a question of this category correctly) ~ Beta. The
belief is one product state — models × categories × Beta(1,1) — updated by Bernoulli
conditioning on observed correctness. A routing decision is EU-max via `skin.optimise`
over a `functional_per_action` preference: a LinearCombination of NestedProjections to
each Beta's mean (= E[θ]), with the per-profile value of a correct answer as `reward`
and the real per-model dollar cost as the action offset:

    EU(model a | category c) = reward · E[θ_{a,c}] − cost_a

All inference runs in the skin (Julia). This module only *declares* structure and *calls*
Tier-1 primitives (create_state / factor / condition / replace_factor / expect / optimise).
Differences from the engine original: (1) `from credence_skin_client import SkinClient`
(the governor's runtime client, same wire) instead of `from skin.client import …`; (2) no
`_ensure_skin_importable` — the caller supplies the client via `build_skin_client()`. Net:
ZERO `credence_router` imports. The probability arithmetic stays in the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type-only; the live client is passed in (build_skin_client()).
    from credence_skin_client import SkinClient


def build_state(skin: "SkinClient", n_models: int, n_categories: int) -> str:
    """Create the routing belief: models × categories × Beta(1,1). Returns a state_id."""
    leaf = {"type": "beta", "alpha": 1.0, "beta": 1.0}
    model = {"type": "product", "factors": [leaf for _ in range(n_categories)]}
    state = {"type": "product", "factors": [model for _ in range(n_models)]}
    return skin.create_state(**state)


def observe_correct(
    skin: "SkinClient", state_id: str, model_idx: int, cat_idx: int, correct: bool
) -> str:
    """Condition θ_{model,cat} on one outcome (correct→1.0 increments α, wrong→0.0 β).
    factor → condition(bernoulli) → replace_factor. Returns the new top-level state_id."""
    model_id = skin.factor(state_id, model_idx)
    cat_id = skin.factor(model_id, cat_idx)
    skin.condition(cat_id, kernel={"type": "bernoulli"}, observation=1.0 if correct else 0.0)
    model_updated = skin.replace_factor(model_id, cat_idx, cat_id)
    return skin.replace_factor(state_id, model_idx, model_updated)


def learned_accuracy(skin: "SkinClient", state_id: str, model_idx: int, cat_idx: int) -> float:
    """E[θ_{model,cat}] — the posterior-mean accuracy, read through `expect`."""
    return skin.expect(
        state_id, function={"type": "nested_projection", "indices": [model_idx, cat_idx]}
    )


def _preference(
    n_models: int,
    n_categories: int,
    cat_weights: list[float],
    costs: list[float],
    reward: float,
) -> dict:
    """functional_per_action spec: EU(a) = reward · Σ_c w_c · E[θ_{a,c}] − cost_a."""
    actions: dict[str, dict] = {}
    for a in range(n_models):
        terms = [
            [reward * cat_weights[c], {"type": "nested_projection", "indices": [a, c]}]
            for c in range(n_categories)
        ]
        actions[str(a)] = {"type": "linear_combination", "terms": terms, "offset": -costs[a]}
    return {"type": "functional_per_action", "actions": actions}


def route(
    skin: "SkinClient",
    state_id: str,
    costs: list[float],
    cat_idx: int,
    reward: float,
    n_categories: int,
) -> int:
    """EU-max model index for a question of category `cat_idx` under `reward` (the profile:
    the $ value of a correct answer). One belief, many utilities (Savage)."""
    n_models = len(costs)
    cat_weights = [0.0] * n_categories
    cat_weights[cat_idx] = 1.0
    pref = _preference(n_models, n_categories, cat_weights, costs, reward)
    actions_spec = {"type": "finite", "values": list(range(n_models))}
    action, _eu = skin.optimise(state_id, actions_spec, pref)
    return int(action) if not isinstance(action, int) else action
