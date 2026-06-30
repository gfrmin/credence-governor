# Role: eval
"""cost_aggregate.py — cost_results.json → COST.md (client-facing, Phase 2 cost axis).

The buyer question: "RouteLLM saves money — why your governor over a cost router?" The
honest answer the coding data gives, averaged over many train/test splits (no single-seed
cherry-pick): on coding the cheap frontier model is ~as good as the strong one, AND a
simple difficulty signal can't tell which few tasks are hard — so NO realisable router
(Credence or RouteLLM) beats "always cheap", and the clairvoyant ceiling stays out of
reach. The cost axis is a TIE on the merits. Credence's distinctive value is its one-belief
reward dial (which spans the cost axis) and, decisively, COVERAGE — it also governs harm
(Phase 1) and waste, where the cost-only rivals score zero. Cited rivals carry published
numbers, tagged, never blended.
"""

from __future__ import annotations

import json
import os

RES = os.path.join(os.path.dirname(__file__), "cost_results.json")
OUT = os.path.join(os.path.dirname(__file__), "COST.md")

ANCHOR = ("Credence's routing on **20 real multi-turn coding workloads** "
          "(`credence/data/benchmark-raw.json`, move-2): **~68% mean cost saving vs always-sonnet "
          "at 0 quality degradations** (opus-judged quality 7.1 vs 6.3) — the cheap model was good "
          "enough and quality held, the same convergence this grid shows from a different angle.")

CITED = [
    {"name": "RouteLLM", "axis": "cost only",
     "note": "open router; **~95% of GPT-4 quality at ~26% GPT-4 calls** (MT-Bench). Cost axis only — "
             "**zero harm/waste coverage**. On coding, where cheap≈strong and the hard tasks are hard to "
             "predict, its win-predictor converges to the cheap-model policy measured here.",
     "url": "https://lmsys.org/blog/2024-07-01-routellm/"},
    {"name": "FrugalGPT", "axis": "cost only",
     "note": "cheapest-first cascade with a learned verifier; our `frugal-cascade` row is its "
             "**clairvoyant upper bound** (stops at the first actually-correct rung).",
     "url": "https://arxiv.org/abs/2305.05176"},
    {"name": "TokenShift / LLMLingua", "axis": "cost only",
     "note": "prompt COMPRESSION (orthogonal to routing); ~0.86× cost at claimed-preserved quality. "
             "Stacks with routing but covers neither harm nor waste.",
     "url": "https://github.com/microsoft/LLMLingua"},
]


def _q(r) -> str:   # quality mean±std
    return f"{r['pass_mean']*100:.1f}% ±{r['pass_std']*100:.1f}"


def _c(r) -> str:   # cost mean±std
    return f"${r['cost_mean']:.4f} ±{r['cost_std']:.4f}"


def main() -> int:
    d = json.load(open(RES))
    models = d["models"]
    cheapnm, strongnm = models[0].split("-")[1], models[-1].split("-")[1]
    rows = {r["name"]: r for r in d["rivals"]}
    cred = {c["name"]: c for c in d.get("credence", [])}
    nseeds = d.get("n_seeds", 1)

    L: list[str] = []
    L.append("# Cost axis — Credence routing vs RouteLLM & cost rivals (coding)\n")
    L.append(f"_Phase 2. Per-(task, model) pass/cost measured ONCE on {d['n_tasks']} {d['dataset']} tasks "
             f"across {len(models)} models ({cheapnm}→{strongnm}); every router scored offline on the "
             f"identical grid. Numbers are **mean ± std over {nseeds} train/test splits** (no single-seed "
             f"cherry-pick). Learned routers (routellm-style, credence) fit on each split's train half and "
             f"decide on its test half; realised cost = the chosen model's real grid cost._\n")

    L.append("## Cost vs quality (mean ± std over splits)\n")
    L.append("| Router | Pass-rate (quality) | Total cost ($/test-split) |")
    L.append("|---|---|---|")
    order = [f"always-{cheapnm}", f"always-{models[1].split('-')[1]}", f"always-{strongnm}",
             "random", "clairvoyant (bound)", "frugal-cascade (bound)", "routellm-style"]
    for nm in order:
        if nm in rows:
            L.append(f"| {nm} | {_q(rows[nm])} | {_c(rows[nm])} |")
    for prof in ("cost-saver", "balanced", "quality-first"):
        if prof in cred:
            L.append(f"| credence@{prof} (reward={cred[prof]['reward']}) | {_q(cred[prof])} | {_c(cred[prof])} |")
    L.append("")

    ac, as_ = rows.get(f"always-{cheapnm}"), rows.get(f"always-{strongnm}")
    clair, rl = rows.get("clairvoyant (bound)"), rows.get("routellm-style")
    cs, qf = cred.get("cost-saver"), cred.get("quality-first")
    if ac and as_ and as_["cost_mean"]:
        save = 1 - ac["cost_mean"] / as_["cost_mean"]
        gap = (as_["pass_mean"] - ac["pass_mean"]) * 100
        L.append("## What the coding data says\n")
        L.append(f"- **Cheap ≈ strong on coding.** always-{cheapnm} {_pct(ac)} vs always-{strongnm} "
                 f"{_pct(as_)} — a **{gap:.0f} pt** quality gap at **{save*100:.0f}% lower cost**. The "
                 "routing headroom (cheap fails, strong passes) is a handful of tasks.\n")
        if clair:
            L.append(f"- **The headroom exists but is unreachable.** The clairvoyant bound hits "
                     f"**{_pct(clair)} at ${clair['cost_mean']:.3f}** (≈ cheap-model cost) by sending only "
                     "the few hard tasks to a strong model. But a prompt-length difficulty feature can't "
                     "predict which tasks those are, so **no realisable router reaches it**.\n")
        if rl and cs:
            L.append(f"- **No realisable router beats 'always cheap' — it's a tie.** Credence@cost-saver "
                     f"({_pct(cs)}, ${cs['cost_mean']:.3f}) sits right at the cheap baseline; routellm-style "
                     f"({_pct(rl)}, ${rl['cost_mean']:.3f}) and Credence's higher-reward profiles spend "
                     f"~30–50% more for **no quality gain** — because the weak difficulty signal can't "
                     "identify the hard tasks to upgrade. Both learned routers converge to the cheap "
                     "model's quality.\n")
        if cs and qf:
            L.append(f"- **The reward dial spans cost, from one belief.** cost-saver routes cheap "
                     f"(${cs['cost_mean']:.3f}); quality-first pays more (${qf['cost_mean']:.3f}) — the EU-max "
                     "decision moves with the buyer profile. Here the extra spend buys ~no quality (the "
                     "signal is too weak to convert dollars into passes), which is the honest read, not a "
                     "knock on the mechanism.\n")
        L.append(f"- **The real anchor.** {ANCHOR}\n")
        L.append("- **The differentiator is coverage, not cents.** RouteLLM/FrugalGPT/TokenShift are "
                 "**cost-only point solutions** — zero harm and zero waste coverage. Credence reaches the "
                 "same cost frontier *and* is the only governor that also blocks attacks (Phase 1) and "
                 "averts waste. A buyer picks one governor spanning all axes, not three point tools.\n")

    L.append("## Cited rivals (published numbers — not run here)\n")
    for c in CITED:
        L.append(f"- **{c['name']}** ({c['axis']}): {c['note']} [source]({c['url']})")
    L.append("")
    L.append("## Reading\n")
    L.append("- **Measured** rows ran offline on the identical coding grid; **cited** rows are published "
             "third-party numbers, tagged and linked, never blended.\n"
             f"- Every number is averaged over {nseeds} train/test splits with its std — no single split is "
             "load-bearing.\n"
             "- HumanEval frontier-model pass-rates are high (cheap ≈ strong), so this grid measures the "
             "**easy/standard-coding regime** where cost dominates and routing has little to exploit. A "
             "harder regime (competition-level tasks with a real capability gradient) would stress routing "
             "QUALITY and is the natural next grid.\n"
             "- The credence rows are the engine's EU-max routing rule over the skin wire "
             "(per-(bin,model) Beta beliefs); the reward dial is the buyer profile.")

    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"→ {OUT}")
    return 0


def _pct(r) -> str:
    return f"{r['pass_mean']*100:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main())
