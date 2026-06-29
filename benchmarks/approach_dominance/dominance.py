# Role: eval
"""Run every (arm × profile × scenario); emit per-cell win/tie/loss verdicts with
measured/modelled tags → routing_results.json.

The Credence arm's routing decisions are made by the skin (skin.optimise over the
Beta-Bernoulli belief in routing_belief.py), reached the same way the daemon reaches it
(build_skin_client). Competitors are declared foils (arms.py). Welfare is scored on
identical ground truth for every arm:

    welfare_P(arm) = Σ_q [ reward_P · 1{correct} − cost ]

Verdict (Credence-routed vs a competitor, under profile P) is the welfare regret with a
declared tie band (§3 no-magic-thresholds) — welfare is the profile's own utility, so
"cheaper at ≥ quality" and "more correct at ≤ cost" both fall out of regret > 0.

G1 (§5.2): a cell is `measured` iff its scenario is measured AND the competitor is
measured (routing class). The **headline** dominance number is computed over the measured
subset only and is asserted measured (§7 halt-the-line) — a synthetic cell can never enter
the marquee claim. Compression-class verdicts are modelled (the honest boundary); the
stacked arm (compression ∘ measured routing) is recorded for the capability-gap triage.

    CREDENCE_ENGINE_DIR=/home/g/git/credence \
      uv run --project packages/governor_core python benchmarks/approach_dominance/dominance.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))  # sibling imports when run as a script

import arms as A
import routing_belief as RB
import scenarios as SC
from profiles import PERSONAS, PRESETS
from synthetic_competitors import SYNTH_COMPRESSOR, best_case, tokenshift_cost_mult

# Declared tie band (§3): a verdict is a tie iff |welfare regret| ≤ max(EPS_ABS, EPS_REL·scale).
EPS_ABS = 1e-9
EPS_REL = 0.005   # 0.5% of the larger welfare magnitude

OUT = os.path.join(os.path.dirname(__file__), "routing_results.json")


def _profiles() -> dict[str, float]:
    """name -> reward (the routing coordinate). Presets ∪ personas."""
    return {name: p.reward for name, p in {**PRESETS, **PERSONAS}.items()}


def welfare(arm, test_qs, reward) -> tuple[float, float, int]:
    """Returns (welfare, total_cost, n_correct) over the test split."""
    cost = 0.0
    correct = 0
    for c, k in map(arm, test_qs):
        correct += 1 if c else 0
        cost += k
    return reward * correct - cost, cost, correct


def _train(skin, scenario, train_ids):
    cat_index = {c: i for i, c in enumerate(scenario.categories)}
    s = RB.build_state(skin, len(scenario.model_names), len(scenario.categories))
    for q in scenario.questions:
        if q.id in train_ids:
            ci = cat_index[q.category]
            for m in range(len(scenario.model_names)):
                s = RB.observe_correct(skin, s, m, ci, scenario.grid[(m, q.id)])
    return s


def _routing_table(skin, scenario, state, reward) -> dict:
    """category → EU-max model under `reward` (route depends on category+reward only)."""
    n_cat = len(scenario.categories)
    return {
        c: RB.route(skin, state, scenario.costs, i, reward, n_cat)
        for i, c in enumerate(scenario.categories)
    }


def _credence_arm(scenario, table):
    return lambda q: (scenario.grid[(table[q.category], q.id)], scenario.costs[table[q.category]])


def _verdict(regret: float, scale: float) -> str:
    band = max(EPS_ABS, EPS_REL * scale)
    if regret > band:
        return "win"
    if regret < -band:
        return "loss"
    return "tie"


def run_scenario(skin, scenario, profiles, compc) -> tuple[list[dict], dict]:
    """Returns (cells, scenario_meta). One cell per (profile × competitor).

    Headline mode is the *calibrated/deployed state*: the belief is conditioned on the full
    measured grid (the state after the flywheel has run), and all arms — Credence and the
    fixed foils alike — are scored on that same grid. This is the Wald complete-class
    demonstration: given calibrated beliefs, EU-max provably weakly dominates every fixed
    rule per profile (it maximises exactly the welfare the verdict scores). Held-out thin-data
    behaviour — where EU-max can trail before the belief converges — is a *calibration* claim,
    demonstrated as its own convergence curve, NOT conflated with the dominance map (on the
    n=50 grid the measured 'scenarios' are subsets of one grid, so a split adds only noise).
    """
    n_models = len(scenario.model_names)
    distinct_rewards = sorted(set(profiles.values()))
    cheapest = min(range(n_models), key=lambda m: scenario.costs[m])
    priciest = max(range(n_models), key=lambda m: scenario.costs[m])
    cascade_order = sorted(range(n_models), key=lambda m: scenario.costs[m])
    full_ids = {q.id for q in scenario.questions}
    test_qs = scenario.questions

    emp = A.empirical_accuracy(scenario.grid, full_ids, scenario.questions, n_models, scenario.categories)
    per_cat = {c: [round(emp[(m, c)][0], 4) for m in range(n_models)] for c in scenario.categories}

    state = _train(skin, scenario, full_ids)
    tables = {r: _routing_table(skin, scenario, state, r) for r in distinct_rewards}

    foils = {
        f"always-{scenario.model_names[cheapest]}": A.make_always(scenario.grid, scenario.costs, cheapest),
        f"always-{scenario.model_names[priciest]}": A.make_always(scenario.grid, scenario.costs, priciest),
        "best-fixed-table": A.make_best_fixed_table(scenario.grid, scenario.costs, emp, scenario.categories, n_models, distinct_rewards),
        "threshold-router": A.make_threshold_router(scenario.grid, scenario.costs, emp, scenario.categories, n_models),
        "oracle-cascade": A.make_oracle_cascade(scenario.grid, scenario.costs, cascade_order),
    }
    compressed_always = [compc(A.make_always(scenario.grid, scenario.costs, k)) for k in range(n_models)]
    tsc = A.tokenshift_compressor()
    tokenshift_always = [tsc(A.make_always(scenario.grid, scenario.costs, k)) for k in range(n_models)]

    acc_arm: dict[str, dict[str, list]] = {}
    for name, reward in profiles.items():
        bucket = acc_arm.setdefault(name, {})
        cred = _credence_arm(scenario, tables[reward])
        stacked = compc(cred)

        def put(label, arm):
            w, cost, corr = welfare(arm, test_qs, reward)
            bucket[label] = [w, cost, corr]

        put("credence", cred)
        put("stacked", stacked)
        for fname, fn in foils.items():
            put(fname, fn)
        put("compression-frontier", max(compressed_always, key=lambda a: welfare(a, test_qs, reward)[0]))
        put("tokenshift", max(tokenshift_always, key=lambda a: welfare(a, test_qs, reward)[0]))

    nseed = 1
    cats = scenario.categories
    scenario_meta = {
        "name": scenario.name, "axis": scenario.axis, "source": scenario.source,
        "headroom": scenario.headroom, "models": scenario.model_names, "costs": scenario.costs,
        "categories": cats, "n_questions": len(scenario.questions),
        "per_category_model_accuracy": per_cat,
    }

    # build verdict cells: credence vs each competitor
    COMPETITORS = {
        "best-fixed-table": ("routing", "measured"),
        "threshold-router": ("routing", "measured"),
        "oracle-cascade": ("routing", "measured"),
        f"always-{scenario.model_names[cheapest]}": ("routing", "measured"),
        f"always-{scenario.model_names[priciest]}": ("routing", "measured"),
        "compression-frontier": ("compression", "modelled"),
        "tokenshift": ("compression", "modelled"),
    }
    cells = []
    for name, reward in profiles.items():
        b = acc_arm[name]
        cred_w, cred_cost, cred_corr = b["credence"][0] / nseed, b["credence"][1] / nseed, b["credence"][2] / nseed
        stk_w, stk_cost, stk_corr = b["stacked"][0] / nseed, b["stacked"][1] / nseed, b["stacked"][2] / nseed
        for comp, (klass, arm_src) in COMPETITORS.items():
            cw, ccost, ccorr = b[comp][0] / nseed, b[comp][1] / nseed, b[comp][2] / nseed
            regret = cred_w - cw
            scale = max(abs(cred_w), abs(cw), 1.0)
            verdict = _verdict(regret, scale)
            # G1: measured iff scenario measured AND competitor measured
            cell_source = "measured" if (scenario.source == "measured" and arm_src == "measured") else "modelled"
            # capability-gap diagnostic input: does stacked close the gap vs this competitor?
            stacked_regret = stk_w - cw
            cells.append({
                "scenario": scenario.name, "axis": scenario.axis, "scenario_source": scenario.source,
                "headroom": scenario.headroom, "profile": name, "reward": reward,
                "competitor": comp, "competitor_class": klass, "arm_source": arm_src,
                "cell_source": cell_source, "verdict": verdict, "regret": round(regret, 6),
                "cost_credence": round(cred_cost, 6), "cost_competitor": round(ccost, 6),
                "correct_credence": round(cred_corr, 3), "correct_competitor": round(ccorr, 3),
                "cost_delta_pct": round(100 * (cred_cost - ccost) / ccost, 2) if ccost else None,
                # triage inputs
                "stacked_cost": round(stk_cost, 6), "stacked_correct": round(stk_corr, 3),
                "stacked_regret_vs_competitor": round(stacked_regret, 6),
                "stacked_verdict_vs_competitor": _verdict(stacked_regret, max(abs(stk_w), abs(cw), 1.0)),
            })
    return cells, scenario_meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competitor-best-case", action="store_true",
                    help="push the compressor past its favourable bound (the steelman re-run)")
    args = ap.parse_args(argv)

    from credence_governor_core import build_skin_client

    synth = best_case(SYNTH_COMPRESSOR) if args.competitor_best_case else SYNTH_COMPRESSOR
    compc = A.make_compressor(synth["cost_mult"], synth["quality_delta"])
    profiles = _profiles()
    scens = SC.all_scenarios()

    skin = build_skin_client()
    skin.initialize()
    all_cells, scenario_metas = [], []
    try:
        for sc in scens:
            cells, meta = run_scenario(skin, sc, profiles, compc)
            all_cells.extend(cells)
            scenario_metas.append(meta)
            print(f"  scenario {sc.name:<26} [{sc.source}/{sc.headroom}]  {len(cells)} cells")
    finally:
        skin.shutdown()

    # ── headline: routing-class dominance over the MEASURED subset only (G1) ──
    # The clairvoyant oracle-cascade is an unattainable upper bound (it sees the answer),
    # so it is reported separately from real routers — the same Wald treatment the engine
    # uses (a clairvoyant arm is excluded from the admissibility check).
    measured = [c for c in all_cells if c["cell_source"] == "measured" and c["competitor_class"] == "routing"]

    def _tally(cells):
        w = sum(1 for c in cells if c["verdict"] == "win")
        t = sum(1 for c in cells if c["verdict"] == "tie")
        l = sum(1 for c in cells if c["verdict"] == "loss")
        n = len(cells)
        return {"n": n, "win": w, "tie": t, "loss": l,
                "weak_dominance": round((w + t) / n, 4) if n else None,
                "strict_win": round(w / n, 4) if n else None}

    real = [c for c in measured if c["competitor"] != "oracle-cascade"]
    bft = [c for c in measured if c["competitor"] == "best-fixed-table"]
    by_comp = {}
    for c in measured:
        by_comp.setdefault(c["competitor"], []).append(c)
    headline = {
        "claim": "Credence routing-class dominance over measured scenarios (weak = win+tie)",
        "source": "measured",
        "measured_cell_count": len(measured),
        "all_routers": _tally(measured),
        "real_routers_excl_clairvoyant_cascade": _tally(real),
        "vs_best_fixed_table_wald_foil": _tally(bft),   # 0 losses ⇒ undominated by the best static table
        "by_competitor": {k: _tally(v) for k, v in sorted(by_comp.items())},
        # back-compat top-line: weak dominance over real routers is the honest marquee number
        "dominance_fraction": _tally(real)["weak_dominance"],
    }
    wins, ties, losses, n = (headline["all_routers"]["win"], headline["all_routers"]["tie"],
                             headline["all_routers"]["loss"], headline["measured_cell_count"])

    result = {
        "epsilon": {"abs": EPS_ABS, "rel": EPS_REL, "note": "tie iff |regret| ≤ max(abs, rel·scale)"},
        "compressor": synth, "competitor_best_case": args.competitor_best_case,
        "tokenshift_cost_mult": round(tokenshift_cost_mult(), 4),
        "n_caveat": {"grid_n": len(SC.load_anchor().questions),
                     "note": "calibrated/deployed-state comparison: belief conditioned on the full measured "
                             "grid (n questions above), all arms scored on that grid (Wald complete-class). "
                             "The measured 'scenarios' are subsets of one n=50 grid — a held-out split would add "
                             "noise, not data; thin-data convergence is a separate calibration claim."},
        "scenarios": scenario_metas,
        "headline": headline,
        "cells": all_cells,
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)

    # §7 halt-the-line: the headline must be measured, over a non-empty measured subset.
    assert headline["source"] == "measured", "headline must be measured"
    assert headline["measured_cell_count"] > 0, "no measured routing-class cells — engine unreachable or degraded to modelled?"
    assert all(c["cell_source"] == "measured" for c in measured), "a headline cell is not measured"
    print(f"\nHEADLINE (measured, n={n}): dominance(weak)={headline['dominance_fraction']} "
          f"win={wins} tie={ties} loss={losses}  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
