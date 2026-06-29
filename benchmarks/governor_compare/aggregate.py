# Role: eval
"""aggregate.py — governor_compare_results.json → COMPARISON.md (client-facing).

One table a buyer can read: every governor's attack recall, its false-block on REAL
developer traffic, its friction, and the $ it spends to govern — plus a measured-vs-CITED
ledger (rivals we ran vs. rivals whose published numbers we cite) and the false-block
investigation. Truth-finding: the cited rows carry their source URL; nothing is blended.
"""

from __future__ import annotations

import json
import os

RES = os.path.join(os.path.dirname(__file__), "governor_compare_results.json")
OUT = os.path.join(os.path.dirname(__file__), "COMPARISON.md")

# Rivals we cannot run in-process (open-weights model needing a GPU, or a paid API) — cited
# with published numbers, tagged CITE, never blended into the measured table. URLs inline.
CITED = [
    {"name": "Llama Guard 3 (8B)", "tier": "real (cite)", "axis": "harm",
     "note": "open-weights safety classifier; high precision but **poor recall on agent/tool-use** "
             "adversarial benchmarks — the allowed-channel class it misses is exactly Credence's gap.",
     "url": "https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Guard3/8B/MODEL_CARD.md"},
    {"name": "Lakera Guard", "tier": "real (cite)", "axis": "harm (prompt-injection)",
     "note": "commercial guardrail; PINT prompt-injection benchmark **92.5%**. Detection only, "
             "not tool-call governance; per-call API cost + latency on the hot path.",
     "url": "https://github.com/lakeraai/pint-benchmark"},
    {"name": "RouteLLM", "tier": "real (cite)", "axis": "cost (Phase 2)",
     "note": "open router; **~95% of GPT-4 quality at ~26% GPT-4 calls** (MT-Bench ~85% cost cut). "
             "Cost axis only — zero harm coverage. Run head-to-head in Phase 2.",
     "url": "https://lmsys.org/blog/2024-07-01-routellm/"},
]


def _pct(x) -> str:
    return "—" if x is None else f"{x*100:.0f}%"


def _pct3(x) -> str:
    return "—" if x is None else f"{x*100:.1f}%"


def main() -> int:
    d = json.load(open(RES))
    rows = d["governors"]
    L: list[str] = []
    L.append("# Governor comparison — concrete numbers vs rival governors\n")
    L.append(f"_Phase 1: harm recall + false-block on real traffic. Benign = {d['benign']['n']} real "
             f"captured Claude Code calls (benign-by-assumption); attack = {d['attack']['n']} declared "
             f"coding red-team. Credence = the real daemon decision over the skin wire._\n")

    L.append("## The table\n")
    L.append("| Governor | Tier | Attack block | Attack catch (＋ask) | False-block (real traffic) | Friction (asks) | $/decision | Latency/decision |")
    L.append("|---|---|---|---|---|---|---|---|")

    def row_line(name: str, r: dict) -> str:
        h, b = r["harm"], r["benign"]
        n_dec = max(1, b.get("n", 1))
        cps = (b.get("decide_cost_total", 0.0) or 0.0) / n_dec
        cost = "~0" if cps < 1e-6 else f"${cps:.5f}"
        lat_s = b.get("latency_mean_s") or 0.0
        lat = "~0" if lat_s < 1e-3 else f"{lat_s:.2f}s"
        return (f"| {name} | {r['tier']} | {_pct(h.get('block_recall'))} | {_pct(h.get('recall'))} "
                f"| {_pct3(b.get('false_block_rate'))} | {_pct(b.get('false_gate_rate'))} | {cost} | {lat} |")

    # order: rivals, then Credence rows
    rivals = [k for k in rows if not k.startswith("credence")]
    creds = [k for k in rows if k.startswith("credence")]
    for k in rivals + creds:
        L.append(row_line(k, rows[k]))
    L.append("")
    L.append("_Attack block = hard-denied; catch = block or ask (interrupted). Friction = share of "
             "real benign calls the governor interrupts. Credence's friction is the governance/waste "
             "brain, which **learns down** per deployment (cold vs deployed rows show the delta)._\n")
    L.append("_The **false-block** column above uses the benign-by-assumption denominator. "
             "[`OUTCOMES.md`](OUTCOMES.md) re-derives it per call from session replay — every block "
             "is grounded as landing on a developer-**accepted**, **reverted**, or **unobserved** "
             "call, so the benign label is earned, not assumed._\n")
    sizes = ", ".join(f"{k} n={rows[k]['benign'].get('n')}" for k in (rivals + creds))
    L.append(f"_Benign sample sizes (false-block denominator) differ by cost of scoring: {sizes}. "
             f"Attack n={d['attack']['n']} for all._\n")

    # Per-threat-class for the headline Credence row, if present.
    head = next((k for k in creds if k.endswith("@shipped")), None) or (creds[0] if creds else None)
    if head and "per_threat_class" in rows[head]["harm"]:
        L.append(f"## Where the attacks land — `{head}`\n")
        L.append("| Threat class | caught / n |")
        L.append("|---|---|")
        for tc, v in rows[head]["harm"]["per_threat_class"].items():
            L.append(f"| {tc} | {v['caught']}/{v['n']} |")
        L.append("")

    # False-block investigation: what Credence stops you doing.
    if head and rows[head]["benign"].get("fp_examples"):
        L.append("## False-block investigation — what Credence blocks on real traffic\n")
        L.append("| tool | command (truncated) | action | target | egress | taint-flow | taint-source |")
        L.append("|---|---|---|---|---|---|---|")
        for e in rows[head]["benign"]["fp_examples"]:
            cmd = (e.get("cmd") or "").replace("|", "\\|").replace("\n", " ")
            L.append(f"| {e.get('tool')} | `{cmd}` | {e.get('action-class')} | {e.get('target')} "
                     f"| {e.get('egress')} | {e.get('taint-flow')} | {e.get('taint-source')} |")
        L.append("")

    # Cited rivals (RUN vs CITE ledger).
    L.append("## Cited rivals (published numbers — not run here)\n")
    for c in CITED:
        L.append(f"- **{c['name']}** ({c['tier']}, {c['axis']}): {c['note']} [source]({c['url']})")
    L.append("")
    L.append("## Reading\n")
    L.append("- **Measured** rows ran in-process on identical records; **cited** rows are published "
             "third-party numbers, tagged and linked, never blended into the measured table.\n"
             "- Benign traffic is benign-by-assumption (validate on a sample); a hard-block on it is a "
             "false-block.\n- Cost/success axes and the per-profile Pareto are Phases 2–4.")

    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
