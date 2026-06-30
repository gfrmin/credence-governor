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


def _rival_picks(grid, models, bins, n_bins, train_ids):
    """The fixed/learned router policies for one split — each a `tid -> model|list`.
    Routers that learn (routellm) see ONLY the train split's per-bin accuracy."""
    cheap, strong = models[0], models[-1]
    acc = _train_bin_acc(grid, train_ids, bins, models, n_bins)
    ci, si = 0, len(models) - 1

    def clairvoyant(tid):
        for m in models:
            if _passed(grid, tid, m):
                return m
        return cheap

    # RouteLLM-style done FAITHFULLY: a cheap-vs-strong WIN predictor — route to the strong
    # model only where its per-bin train accuracy actually EXCEEDS the cheap one's (margin>0).
    # (The earlier midpoint-of-cheap-accuracy cut routed the low bin to strong even when the
    # belief said strong was no better — a strawman that manufactured a cost gap; this ties
    # the cheap baseline exactly when the models are per-bin indistinguishable.)
    rl_pick = {b: (strong if acc[(si, b)] - acc[(ci, b)] > 0 else cheap) for b in range(n_bins)}

    picks = {f"always-{m.split('-')[1]}": (lambda t, m=m: m) for m in models}
    picks["clairvoyant (bound)"] = clairvoyant
    picks["frugal-cascade (bound)"] = lambda t: list(models)
    picks["routellm-style"] = lambda t: rl_pick[bins[t]]
    return picks


def _aggregate(samples: dict[str, dict[str, list]]) -> list[dict]:
    """{name: {'pass':[...], 'cost':[...]}} → mean±std rows across the seed sweep."""
    out = []
    for name, s in samples.items():
        out.append({"name": name, "n_seeds": len(s["pass"]),
                    "pass_mean": round(statistics.mean(s["pass"]), 4),
                    "pass_std": round(statistics.pstdev(s["pass"]), 4) if len(s["pass"]) > 1 else 0.0,
                    "cost_mean": round(statistics.mean(s["cost"]), 5),
                    "cost_std": round(statistics.pstdev(s["cost"]), 5) if len(s["cost"]) > 1 else 0.0})
    return out


def main(argv=None) -> int:
    import argparse
    from collections import defaultdict
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default=O.GRID)
    ap.add_argument("--seeds", type=int, default=25, help="train/test splits to average over (kills single-seed cherry-pick)")
    ap.add_argument("--skip-credence", action="store_true")
    args = ap.parse_args(argv)

    grid = O.load_grid(args.grid)
    models = list(O.ROSTER)                                  # [haiku, sonnet, opus] cheap→strong
    task_ids = sorted({tid for (tid, _m) in grid})
    tasks = [t for t in D.load_tasks() if t.task_id in task_ids]
    bins = difficulty_bins(tasks)
    n_bins = max(bins.values()) + 1
    mean_cost = {m: statistics.mean([_cost(grid, t, m) for t in task_ids]) for m in models}
    seeds = list(range(args.seeds))
    splits = {s: (lambda tr_te: (tr_te[0], sorted(tr_te[1])))(_split(task_ids, seed=s)) for s in seeds}
    print(f"grid: {len(task_ids)} tasks × {len(models)} models; {len(seeds)} seeds; "
          f"mean cost/task: " + "  ".join(f"{m.split('-')[1]}=${mean_cost[m]:.4f}" for m in models))

    riv: dict[str, dict[str, list]] = defaultdict(lambda: {"pass": [], "cost": []})
    for s in seeds:
        train_ids, test_ids = splits[s]
        picks = _rival_picks(grid, models, bins, n_bins, train_ids)
        rng = random.Random(s)
        picks["random"] = lambda t: rng.choice(models)
        for name, choose in picks.items():
            r = score(name, choose, test_ids, grid, models)
            riv[name]["pass"].append(r["pass_rate"])
            riv[name]["cost"].append(r["total_cost"])

    result = {"phase": "2 — cost/quality routing on a coding grid (seed-swept)",
              "dataset": "HumanEval (executable tests)", "models": models,
              "mean_cost_per_task": {m: round(mean_cost[m], 6) for m in models},
              "n_tasks": len(task_ids), "n_bins": n_bins, "n_seeds": len(seeds),
              "rivals": _aggregate(riv)}

    if not args.skip_credence:
        try:
            result["credence"] = _credence_sweep(grid, models, bins, n_bins, splits, mean_cost)
        except Exception as e:
            print(f"  (credence skin router skipped: {e})")
            result["credence_error"] = str(e)

    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    for r in result["rivals"]:
        print(f"  {r['name']:<26} pass={r['pass_mean']:.1%}±{r['pass_std']:.1%}  cost=${r['cost_mean']:.4f}±{r['cost_std']:.4f}")
    for cr in result.get("credence", []):
        print(f"  credence@{cr['name']:<18} pass={cr['pass_mean']:.1%}±{cr['pass_std']:.1%}  "
              f"cost=${cr['cost_mean']:.4f}±{cr['cost_std']:.4f}")
    print(f"→ {OUT}")
    return 0


def _credence_sweep(grid, models, bins, n_bins, splits, mean_cost) -> list[dict]:
    """The real EU-max router over the skin, swept over BOTH the buyer reward profiles and the
    seed splits: per-(model,bin) Beta belief conditioned on each split's TRAIN outcomes, then
    route(reward) per TEST task. One skin session; mean±std per profile across seeds."""
    from collections import defaultdict
    import routing_belief as RB
    from credence_governor_core import build_skin_client

    costs = [mean_cost[m] for m in models]                  # decision uses mean cost; scoring uses real cost
    samples: dict[str, dict[str, list]] = defaultdict(lambda: {"pass": [], "cost": []})
    skin = build_skin_client()
    try:
        for train_ids, test_ids in splits.values():
            state = RB.build_state(skin, len(models), n_bins)
            for tid in train_ids:                           # condition the belief on this split's train
                b = bins[tid]
                for mi, m in enumerate(models):
                    state = RB.observe_correct(skin, state, mi, b, _passed(grid, tid, m))
            for profile, reward in PROFILE_REWARDS.items():
                pick = {tid: models[RB.route(skin, state, costs, bins[tid], reward, n_bins)] for tid in test_ids}
                r = score(f"credence@{profile}", lambda t: pick[t], test_ids, grid, models)
                samples[profile]["pass"].append(r["pass_rate"])
                samples[profile]["cost"].append(r["total_cost"])
        rows = _aggregate(samples)
        for row in rows:
            row["reward"] = PROFILE_REWARDS[row["name"]]
        return rows
    finally:
        skin.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
