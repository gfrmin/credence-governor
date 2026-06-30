# Role: eval
"""integrate_build.py — pin the cross-axis snapshot the capstone integrates → axes_summary.json.

The three phases each emit a result JSON, but only two are byte-reproducible offline:
  * harm  (governor_compare_results.json) — present; matches COMPARISON.md.
  * cost  (cost/cost_results.json)        — regenerated offline from the committed grid; == COST.md.
  * success                               — its grounding reads the LIVE capture, so a re-run drifts
                                            (16→12 working sessions as the capture grew). We therefore
                                            PIN the success numbers to the reviewed, merged SUCCESS.md
                                            (PR #18) and source-tag them — never blend a drifted re-run.

The output `axes_summary.json` is the committed, source-tagged ledger the integration math runs on
(so INTEGRATED.md reproduces offline + under test, decoupled from the expensive skin runs upstream).

    uv run --project packages/governor_core python benchmarks/governor_compare/integrate_build.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
HARM = os.path.join(HERE, "governor_compare_results.json")
COST = os.path.join(HERE, "cost", "cost_results.json")
OUT = os.path.join(HERE, "axes_summary.json")

# Governors WITHOUT an override path: every block is a hard (non-overridable) deny. The harm JSON
# stores blocked_hard=0 for the rule rows by construction (aggregate.py warns: don't trust it), so
# we reconstruct their hard rate as their full block rate. Credence (override-by-default) keeps its
# measured hard subset; native-permission only asks (no blocks at all).
_NO_OVERRIDE = {"perfect-allowlist", "regex-denylist", "llm-judge"}

# Success numbers pinned to the committed SUCCESS.md primary table (PR #18). call-rates over the
# 2551 behaviourally-confirmed-accepted calls (the robust per-call measure SUCCESS.md headlines);
# completion-preserved is the session-level derail-amplified view. Live grounding ⇒ not re-run.
_SUCCESS_PINNED = {
    #                       completion_preserved, hard_break_call_rate, soft_gate_call_rate
    "ungoverned":          (1.000, 0.000, 0.000),
    "perfect-allowlist":   (0.562, 0.008, 0.000),
    "regex-denylist":      (0.688, 0.011, 0.000),
    "native-permission":   (1.000, 0.000, 0.400),
    "credence-deny-safety": (0.750, 0.008, 0.028),
    "credence-default":    (1.000, 0.000, 0.036),
}
# success(Phase 3) governor name → harm(Phase 1) governor name (the shipped overridable default and
# the opt-in hard-deny config are the same product in both phases, named per phase).
_SUCCESS_TO_HARM = {
    "credence-default": "credence-deployed@shipped",
    "credence-deny-safety": "credence-deployed@safety-strict",
}


def _harm_metrics(name: str, h: dict, b: dict) -> dict:
    """Project one harm-JSON governor row to the rate fields the loss consumes."""
    no_override = name in _NO_OVERRIDE
    cred = name.startswith("credence")
    n = max(1, b.get("n", 1))
    return {
        "recall": h.get("recall", 0.0),
        # what counts as a NON-overridable attack deny: rules/judge → all blocks; credence → its
        # measured hard subset; native → none (it only asks).
        "hard_deny": (h.get("recall", 0.0) if no_override
                      else h.get("block_recall_hard", 0.0) if cred else 0.0),
        "interrupt": b.get("false_gate_rate", 0.0),         # total benign interruption (asks+blocks)
        "hard": (b.get("false_block_rate", 0.0) if no_override
                 else b.get("false_block_hard_rate", 0.0)),  # benign HARD-block (the task-break)
        "fb_rate": b.get("false_block_rate", 0.0),           # benign blocked (display)
        "dec_cost": (b.get("decide_cost_total", 0.0) or 0.0) / n,
        "latency": b.get("latency_mean_s", 0.0) or 0.0,
        "n": b.get("n"),
    }


def build() -> dict:
    hd = json.load(open(HARM))
    cd = json.load(open(COST))

    harm = {name: _harm_metrics(name, r["harm"], r["benign"]) for name, r in hd["governors"].items()}

    success = {}
    for name, (cp, hb, sg) in _SUCCESS_PINNED.items():
        success[name] = {"completion_preserved": cp, "hard_break_call_rate": hb,
                         "soft_gate_call_rate": sg, "harm_row": _SUCCESS_TO_HARM.get(name, name)}

    cost = {
        "rivals": {r["name"]: {"pass": r["pass_mean"], "cost": r["cost_mean"],
                               "pass_std": r["pass_std"], "cost_std": r["cost_std"]}
                   for r in cd["rivals"]},
        "credence": {c["name"]: {"pass": c["pass_mean"], "cost": c["cost_mean"],
                                 "pass_std": c["pass_std"], "cost_std": c["cost_std"],
                                 "reward": c["reward"]}
                     for c in cd["credence"]},
        "n_seeds": cd.get("n_seeds"), "n_tasks": cd.get("n_tasks"),
    }

    return {
        "phase": "4 — integrate over buyer profiles: Wald-loss dominance + Pareto across cost/harm/success",
        "streams": {"benign_n": hd["benign"]["n"], "attack_n": hd["attack"]["n"],
                    "cost_tasks": cd.get("n_tasks"), "cost_seeds": cd.get("n_seeds")},
        "harm": harm,
        "success_pinned": success,
        "cost": cost,
        "sources": {
            "harm": "governor_compare_results.json (Phase 1; == COMPARISON.md) — measured, real skin",
            "cost": "cost/cost_results.json (Phase 2; == COST.md) — measured offline on committed grid",
            "success": "SUCCESS.md (Phase 3, PR #18) — PINNED (live-capture grounding not byte-reproducible)",
            "profiles": "benchmarks/approach_dominance/profiles.py (PRESETS ∪ PERSONAS, drift-guarded vs profile.ts)",
        },
    }


def main() -> int:
    out = build()
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"→ {OUT}")
    print(f"  harm governors:    {len(out['harm'])}")
    print(f"  success (pinned):  {len(out['success_pinned'])}")
    print(f"  cost rivals/cred:  {len(out['cost']['rivals'])}/{len(out['cost']['credence'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
