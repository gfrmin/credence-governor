# Role: eval
"""cost_compare.py — score every router on the identical coding grid → cost_results.json.

Phase 2 (cost axis). The oracle grid (oracle.py) holds per-(task, model) {passed, cost},
measured once. Every router is then scored OFFLINE on that identical grid — the apples-to-
apples invariant — so cost/quality differences are the router's decision, not model noise.

Routers (each: per task, pick a model; we charge the model's REAL grid cost and take its
real pass/fail):
  * always-{haiku,sonnet,opus}   — fixed baselines (cost floor / quality ceiling points)
  * random                       — a sanity floor
  * clairvoyant                  — cheapest model that passes (the cost-quality CEILING bound)
  * frugal-cascade               — FrugalGPT cheapest-first escalation, cumulative cost (clairvoyant)
  * routellm-style               — RouteLLM's binary difficulty-threshold router (cheap vs strong)
  * credence                     — the engine's EU-max router over the skin wire: per-(bin,model)
                                   Beta beliefs fit on TRAIN, EU=reward·E[pass]−cost on TEST,
                                   reward swept across buyer profiles to trace its cost-quality curve

Routers that learn (routellm-style, credence) fit on a TRAIN split and decide on TEST; the
difficulty "bin" each conditions on is a pre-execution prompt feature (length quantile) — a
real router sees the query, never the outcome. Decision cost uses each model's mean grid
cost; the REALISED cost charged is the actual per-(task,model) grid cost.

    CREDENCE_ENGINE_DIR=/home/g/git/credence \
      uv run --project packages/governor_core python benchmarks/governor_compare/cost/cost_compare.py
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "approach_dominance"))

import dataset as D
import oracle as O

OUT = os.path.join(os.path.dirname(__file__), "cost_results.json")
N_BINS = 3
PROFILE_REWARDS = {  # buyer profiles: the routing reward dial (presets ∪ personas, profiles.py)
    "cost-saver": 0.02, "indie-hacker": 0.02, "balanced": 1.0,
    "regulated-enterprise": 2.0, "quality-first": 5.0, "fintech-safety": 5.0,
}


def difficulty_bins(tasks: list[D.CodingTask], n_bins: int = N_BINS) -> dict[str, int]:
    """Assign each task a difficulty bin from a PRE-EXECUTION feature (prompt length) —
    outcome-independent, so quantile boundaries over all tasks are not label leakage."""
    lengths = sorted(len(t.prompt) for t in tasks)
    cuts = [lengths[int(len(lengths) * (i + 1) / n_bins) - 1] for i in range(n_bins)]
    out: dict[str, int] = {}
    for t in tasks:
        b = next((i for i, c in enumerate(cuts) if len(t.prompt) <= c), n_bins - 1)
        out[t.task_id] = b
    return out


def _split(task_ids: list[str], seed: int = 7, frac: float = 0.5) -> tuple[set[str], set[str]]:
    ids = list(task_ids)
    random.Random(seed).shuffle(ids)
    k = int(len(ids) * frac)
    return set(ids[:k]), set(ids[k:])


def _passed(grid, tid, model) -> bool:
    c = grid.get((tid, model))
    return bool(c and c.passed)


def _cost(grid, tid, model) -> float:
    c = grid.get((tid, model))
    return c.cost if c else 0.0


def score(name: str, choose, test_ids: list[str], grid, models) -> dict:
    """Charge each test task the chosen model's real cost + take its real pass/fail.
    `choose(tid) -> model | list[model]` (a list = a cascade, charged cumulatively)."""
    total_cost = 0.0
    passed = 0
    for tid in test_ids:
        pick = choose(tid)
        if isinstance(pick, list):                       # cascade: pay each rung, stop at first pass
            ok = False
            for m in pick:
                total_cost += _cost(grid, tid, m)
                if _passed(grid, tid, m):
                    ok = True
                    break
            passed += ok
        else:
            total_cost += _cost(grid, tid, pick)
            passed += _passed(grid, tid, pick)
    n = len(test_ids)
    return {"name": name, "n": n, "pass_rate": round(passed / n, 4) if n else None,
            "total_cost": round(total_cost, 5), "cost_per_task": round(total_cost / n, 6) if n else None}


def _train_bin_acc(grid, train_ids, bins, models, n_bins) -> dict[tuple[int, int], float]:
    """Per-(model_idx, bin) pass-rate on the TRAIN split (the learned signal)."""
    acc: dict[tuple[int, int], float] = {}
    for mi, m in enumerate(models):
        for b in range(n_bins):
            ids = [t for t in train_ids if bins[t] == b]
            acc[(mi, b)] = (sum(_passed(grid, t, m) for t in ids) / len(ids)) if ids else 0.5
    return acc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default=O.GRID)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--skip-credence", action="store_true")
    args = ap.parse_args(argv)

    grid = O.load_grid(args.grid)
    models = list(O.ROSTER)                                  # [haiku, sonnet, opus] cheap→strong
    cheap, strong = models[0], models[-1]
    task_ids = sorted({tid for (tid, _m) in grid})
    tasks = [t for t in D.load_tasks() if t.task_id in task_ids]
    bins = difficulty_bins(tasks)
    n_bins = max(bins.values()) + 1
    train_ids, test_ids = _split(task_ids, seed=args.seed)
    test_ids = sorted(test_ids)
    mean_cost = {m: statistics.mean([_cost(grid, t, m) for t in task_ids]) for m in models}
    print(f"grid: {len(task_ids)} tasks × {len(models)} models; train={len(train_ids)} test={len(test_ids)}; "
          f"mean cost/task: " + "  ".join(f"{m.split('-')[1]}=${mean_cost[m]:.4f}" for m in models))

    rows: list[dict] = []
    # fixed baselines + random + clairvoyant + cascade
    for m in models:
        rows.append(score(f"always-{m.split('-')[1]}", lambda t, m=m: m, test_ids, grid, models))
    rng = random.Random(args.seed)
    rows.append(score("random", lambda t: rng.choice(models), test_ids, grid, models))

    def clairvoyant(tid):                                    # cheapest model that passes (ceiling bound)
        for m in models:
            if _passed(grid, tid, m):
                return m
        return cheap
    rows.append(score("clairvoyant (bound)", clairvoyant, test_ids, grid, models))
    rows.append(score("frugal-cascade (bound)", lambda t: list(models), test_ids, grid, models))

    # RouteLLM-style: binary cheap-vs-strong, per-bin threshold learned on train.
    acc = _train_bin_acc(grid, train_ids, bins, models, n_bins)
    ci, si = 0, len(models) - 1
    cheap_acc = {b: acc[(ci, b)] for b in range(n_bins)}
    cut = (min(cheap_acc.values()) + max(cheap_acc.values())) / 2.0
    rl_pick = {b: (cheap if cheap_acc[b] >= cut else strong) for b in range(n_bins)}
    rows.append(score("routellm-style", lambda t: rl_pick[bins[t]], test_ids, grid, models))

    result = {"phase": "2 — cost/quality routing on a coding grid",
              "dataset": "HumanEval (executable tests)", "models": models,
              "mean_cost_per_task": {m: round(mean_cost[m], 6) for m in models},
              "n_tasks": len(task_ids), "n_bins": n_bins,
              "train": len(train_ids), "test": len(test_ids), "rivals": rows}

    # Credence: the engine's EU-max router over the skin wire, reward swept across profiles.
    if not args.skip_credence:
        try:
            result["credence"] = _run_credence(grid, models, bins, n_bins, train_ids, test_ids, mean_cost)
        except Exception as e:
            print(f"  (credence skin router skipped: {e})")
            result["credence_error"] = str(e)

    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    for r in rows:
        print(f"  {r['name']:<26} pass={r['pass_rate']:.1%}  cost=${r['total_cost']:.4f}  ${r['cost_per_task']:.5f}/task")
    for cr in result.get("credence", []):
        print(f"  credence@{cr['profile']:<18} pass={cr['pass_rate']:.1%}  cost=${cr['total_cost']:.4f}  "
              f"${cr['cost_per_task']:.5f}/task")
    print(f"→ {OUT}")
    return 0


def _run_credence(grid, models, bins, n_bins, train_ids, test_ids, mean_cost) -> list[dict]:
    """The real EU-max router over the skin: per-(model,bin) Beta belief conditioned on TRAIN
    outcomes, then route(reward) per TEST task's bin. Reward swept across buyer profiles."""
    import routing_belief as RB
    from credence_governor_core import build_skin_client

    skin = build_skin_client()
    try:
        state = RB.build_state(skin, len(models), n_bins)
        for tid in train_ids:                               # condition the belief on train outcomes
            b = bins[tid]
            for mi, m in enumerate(models):
                state = RB.observe_correct(skin, state, mi, b, _passed(grid, tid, m))
        costs = [mean_cost[m] for m in models]              # decision uses mean cost; scoring uses real cost
        out: list[dict] = []
        for profile, reward in PROFILE_REWARDS.items():
            pick = {tid: models[RB.route(skin, state, costs, bins[tid], reward, n_bins)] for tid in test_ids}
            row = score(f"credence@{profile}", lambda t: pick[t], test_ids, grid, models)
            row["profile"], row["reward"] = profile, reward
            out.append(row)
        return out
    finally:
        skin.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
