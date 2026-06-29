# Role: eval
"""Loss triage (§App-D — the centerpiece). Every loss cell gets a mechanical cause; a
loss with no cause is a hard error.

Three diagnostics, run in order; the first that fires assigns the cause:

  1. **Artifact** (cheapest, first). A routing-class loss to the *clairvoyant* oracle-cascade
     (an unattainable upper bound, not a real router), or a routing-class loss in a scenario
     with no routing headroom (one model strictly dominates → routing is worthless by
     construction) → `artifact`. Not a product signal.
  2. **Capability-gap.** A *compression-class* loss the STACKED arm (Credence ∘ compression)
     recovers — Credence-alone loses but Credence∘compression wins or ties → `capability-gap`
     (lever = compression). This is the backlog: build the lever; the EU-max already knows when.
  3. **Calibration** (last; fixed budget §5.6). A routing-class loss re-run with the belief
     warmed ONLY on *other measured scenarios'* data (leave-one-scenario-out — never the test
     cell's own outcomes, deterministic order, single application, same ε). If the gap closes →
     `calibration`. A flywheel claim: a deterministic competitor cannot draw the convergence curve.

If none fire → `capability-gap (unknown lever)` by default and the cell is flagged for manual
review (the bias is deliberately *toward* admitting a real gap). A run reporting ZERO
capability-gaps is itself flagged — a truth-finding bench that finds none has likely mis-triaged.

    CREDENCE_ENGINE_DIR=/home/g/git/credence \
      uv run --project packages/governor_core python benchmarks/approach_dominance/loss_triage.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import arms as A
import routing_belief as RB
import scenarios as SC
from dominance import EPS_ABS, EPS_REL, _verdict, welfare

RESULTS = os.path.join(os.path.dirname(__file__), "routing_results.json")
OUT = os.path.join(os.path.dirname(__file__), "loss_triage.json")


def _scenario_has_headroom(scenario_meta) -> bool:
    """Routing has somewhere to go iff some category is best-served by a non-priciest model,
    i.e. a cheaper model is also (at least as) correct. Read off per-category model accuracy."""
    accs = scenario_meta["per_category_model_accuracy"]
    n = len(scenario_meta["models"])
    priciest = max(range(n), key=lambda m: scenario_meta["costs"][m])
    for c, per_model in accs.items():
        best = max(range(n), key=lambda m: per_model[m])
        # a cheaper model ties the best within a small margin ⇒ headroom exists on this cell
        if best != priciest or any(per_model[m] >= per_model[priciest] - 1e-9 and scenario_meta["costs"][m] < scenario_meta["costs"][priciest] for m in range(n)):
            return True
    return False


def _diagnostic_1_2(cell, meta_by_name) -> tuple[str | None, str]:
    """Artifact + capability-gap (no skin). Returns (cause|None, evidence)."""
    if cell["competitor_class"] == "routing":
        if cell["competitor"] == "oracle-cascade":
            return "artifact", "loss to the clairvoyant oracle-cascade — an unattainable upper bound, not a real router"
        if not _scenario_has_headroom(meta_by_name[cell["scenario"]]):
            return "artifact", "no routing headroom in this scenario (one model strictly dominates) — routing worthless by construction"
        return None, ""  # routing loss with headroom → calibration (diagnostic 3)
    if cell["competitor_class"] == "compression":
        if cell["stacked_verdict_vs_competitor"] in ("win", "tie"):
            return ("capability-gap",
                    f"compression-class loss; stacked (Credence∘compression) {cell['stacked_verdict_vs_competitor']}s the "
                    f"competitor (stacked_regret={cell['stacked_regret_vs_competitor']:+.4f}) — the lever (compression) closes it")
        return None, ""  # compression loss stacked does NOT close → default (flagged)
    return None, ""


# ── calibration diagnostic (skin) — fixed split, leakage-excluded warm ────────
# §5.6 ruling: warm only on OTHER data, never the test cell's; fixed N, deterministic,
# single application, same ε, no search. The mix/difficulty scenarios are subsets of the
# anchor, so a naive leave-one-scenario-out would leak the anchor's own outcomes. We instead
# split the target deterministically (first half by id = warm, second half = held-out test),
# and EXCLUDE the test ids from the cross-scenario warm too — so the test outcomes never warm
# the belief. The warm set is then strictly larger than the original thin split (the flywheel).
def _split(scenario):
    ids = sorted(q.id for q in scenario.questions)
    half = max(1, len(ids) // 2)
    return set(ids[:half]), set(ids[half:]) or set(ids[:half])  # warm_ids, test_ids


def _warm_state(skin, target, measured, test_ids, n_models):
    """Belief over the TARGET's own categories, warmed on the target's warm-half PLUS every
    other measured scenario's questions in the SAME categories — excluding any id in
    `test_ids` (no leakage). Synthetic categories appear in no other scenario, so a synthetic
    target self-warms on its warm-half only. Deterministic (category, id) order."""
    local = {c: i for i, c in enumerate(target.categories)}
    s = RB.build_state(skin, n_models, len(local))
    obs, seen = [], set()
    for sc in measured + [target]:
        for q in sc.questions:
            if q.id in test_ids or q.category not in local or (sc.name, q.id) in seen:
                continue
            seen.add((sc.name, q.id))
            obs.append((local[q.category], q.id, sc))
    for ci, qid, sc in sorted(obs, key=lambda t: (t[0], t[1])):
        for m in range(n_models):
            s = RB.observe_correct(skin, s, m, ci, sc.grid[(m, qid)])
    return s, local


def _competitor_arm(scenario, comp, train_ids, distinct_rewards):
    """Rebuild a routing competitor trained on `train_ids` only (never the test half)."""
    n = len(scenario.model_names)
    emp = A.empirical_accuracy(scenario.grid, train_ids, scenario.questions, n, scenario.categories)
    cheapest = min(range(n), key=lambda m: scenario.costs[m])
    priciest = max(range(n), key=lambda m: scenario.costs[m])
    cascade = sorted(range(n), key=lambda m: scenario.costs[m])
    table = {
        f"always-{scenario.model_names[cheapest]}": A.make_always(scenario.grid, scenario.costs, cheapest),
        f"always-{scenario.model_names[priciest]}": A.make_always(scenario.grid, scenario.costs, priciest),
        "best-fixed-table": A.make_best_fixed_table(scenario.grid, scenario.costs, emp, scenario.categories, n, distinct_rewards),
        "threshold-router": A.make_threshold_router(scenario.grid, scenario.costs, emp, scenario.categories, n),
        "oracle-cascade": A.make_oracle_cascade(scenario.grid, scenario.costs, cascade),
    }
    return table.get(comp)


def _compression_competitor(scenario, comp_name, test_qs, reward, compc, tsc):
    """Rebuild the compression-class competitor on the test half (best compressed-always-k,
    same selection as dominance.py: the single fixed model whose compressed welfare is best)."""
    n = len(scenario.model_names)
    wrap = compc if comp_name == "compression-frontier" else tsc
    arms_k = [wrap(A.make_always(scenario.grid, scenario.costs, k)) for k in range(n)]
    return max(arms_k, key=lambda a: welfare(a, test_qs, reward)[0])


def main() -> int:
    data = json.load(open(RESULTS))
    cells = data["cells"]
    meta_by_name = {m["name"]: m for m in data["scenarios"]}
    losses = [c for c in cells if c["verdict"] == "loss"]

    n_models = len(SC.load_anchor().model_names)
    scen_by_name = {s.name: s for s in SC.all_scenarios()}
    measured = [s for s in SC.all_scenarios() if s.source == "measured"]

    # use the SAME compressor params that generated this routing_results.json (so a
    # --competitor-best-case triage matches its run).
    from synthetic_competitors import SYNTH_COMPRESSOR
    cp = data.get("compressor", SYNTH_COMPRESSOR)
    compc = A.make_compressor(cp["cost_mult"], cp.get("quality_delta", 0.0))
    tsc = A.tokenshift_compressor()

    triaged, need_calib = [], []
    for cell in losses:
        cause, evidence = _diagnostic_1_2(cell, meta_by_name)
        if cause:
            triaged.append({**_key(cell), "cause": cause, "evidence": evidence})
        else:
            # Routing losses with headroom → calibration (warmed-credence vs competitor).
            # Compression losses the thin-routing stacked arm didn't close → re-test with a
            # WARMED belief: stacked∘calibrated-routing closing proves the lever (compression)
            # closes it (capability-gap), not a deeper gap. Both go through the warmed skin path.
            need_calib.append(cell)

    # calibration: one warmed belief per (scenario, reward), test on the held-out half (skin)
    if need_calib:
        from credence_governor_core import build_skin_client
        skin = build_skin_client()
        skin.initialize()
        try:
            by_scen: dict[str, list] = {}
            for c in need_calib:
                by_scen.setdefault(c["scenario"], []).append(c)
            for scen_name, group in by_scen.items():
                scenario = scen_by_name[scen_name]
                warm_ids, test_ids = _split(scenario)
                test_qs = [q for q in scenario.questions if q.id in test_ids]
                train_ids = {q.id for q in scenario.questions} - test_ids  # competitor train = non-test
                state, local = _warm_state(skin, scenario, measured, test_ids, n_models)
                rewards = sorted({c["reward"] for c in group})
                tables = {
                    r: {c: RB.route(skin, state, scenario.costs, local[c], r, len(local)) for c in scenario.categories}
                    for r in rewards
                }
                for cell in group:
                    r, table = cell["reward"], tables[cell["reward"]]
                    cred = lambda q, t=table: (scenario.grid[(t[q.category], q.id)], scenario.costs[t[q.category]])
                    is_comp = cell["competitor_class"] == "compression"
                    if is_comp:  # stacked = compression ∘ calibrated routing, vs the compressor
                        cred_side = compc(cred)
                        comp_arm = _compression_competitor(scenario, cell["competitor"], test_qs, r, compc, tsc)
                    else:        # calibrated routing vs the routing foil
                        cred_side = cred
                        comp_arm = _competitor_arm(scenario, cell["competitor"], train_ids, rewards)
                    cred_w, _, _ = welfare(cred_side, test_qs, r)
                    comp_w, _, _ = welfare(comp_arm, test_qs, r)
                    regret = cred_w - comp_w
                    closed = _verdict(regret, max(abs(cred_w), abs(comp_w), 1.0)) in ("win", "tie")
                    if is_comp and closed:
                        triaged.append({**_key(cell), "cause": "capability-gap",
                                        "evidence": f"warmed stacked (compression ∘ calibrated routing) closes the compressor on the "
                                                    f"held-out half (regret {cell['regret']:+.4f} → {regret:+.4f}) — the lever (compression) closes it"})
                    elif (not is_comp) and closed:
                        triaged.append({**_key(cell), "cause": "calibration",
                                        "evidence": f"belief warmed cross-scenario (test ids held out) → Credence closes the "
                                                    f"competitor on the held-out half (regret {cell['regret']:+.4f} → {regret:+.4f})"})
                    else:
                        lever = "even warmed stacked still loses to the compressor" if is_comp else "warmed routing still loses"
                        triaged.append({**_key(cell), "cause": "capability-gap (unknown lever)",
                                        "evidence": f"survived artifact+capability+calibration; {lever} (held-out regret "
                                                    f"{regret:+.4f}) — flagged for manual review",
                                        "flag": "manual-review"})
        finally:
            skin.shutdown()

    # ── integrity gates ──
    causes = [t["cause"] for t in triaged]
    n_capgap = sum(1 for c in causes if c.startswith("capability-gap"))
    flags = [t for t in triaged if t.get("flag")]
    summary = {
        "n_losses": len(losses), "n_triaged": len(triaged),
        "by_cause": {k: causes.count(k) for k in sorted(set(causes))},
        "n_capability_gap": n_capgap,
        "zero_capability_gap_flag": (n_capgap == 0),  # a bench finding NO gaps has likely mis-triaged
        "manual_review_flags": [t["evidence"] for t in flags],
    }
    json.dump({"summary": summary, "triaged": triaged}, open(OUT, "w"), indent=2)

    # §3: every loss cell must carry a cause (an untriaged loss is the one intolerable state).
    assert len(triaged) == len(losses), f"untriaged losses: {len(losses) - len(triaged)}"
    print(f"triage: {len(losses)} losses → {summary['by_cause']}")
    if summary["zero_capability_gap_flag"]:
        print("  ⚠ ZERO capability-gaps — flagged: a truth-finding bench finding no gaps has likely mis-triaged.")
    if flags:
        print(f"  ⚠ {len(flags)} loss(es) defaulted to capability-gap(unknown) — flagged for manual review.")
    print(f"  → {OUT}")
    return 0


def _key(cell) -> dict:
    return {k: cell[k] for k in ("scenario", "profile", "competitor", "competitor_class",
                                 "verdict", "regret", "cost_delta_pct", "cell_source")}


if __name__ == "__main__":
    raise SystemExit(main())
