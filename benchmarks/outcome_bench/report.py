"""report.py — outcome_bench_results.json → OUTCOME_BENCH.md. Every number
in the page comes from the results JSON (the integrate_aggregate
discipline: no hand-claims); the caveats register is the one static text.

Run:
    uv run --project packages/governor_core python benchmarks/outcome_bench/report.py
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_JSON = os.path.join(HERE, "outcome_bench_results.json")
OUT_MD = os.path.join(HERE, "OUTCOME_BENCH.md")

CAVEATS = """\
## The caveats register (binding on any reading of the numbers)

1. **Realized-state assignment**: accepted ⇒ the wanted column, reverted ⇒
   the wasteful column of the engine's own step table (`membrane.utility_rows`;
   block-on-accepted = λc, proceed-on-reverted = c, ask = q flat). Reverted is
   the log's only high-precision "unwanted" signal (explicit undo within 12
   calls); acceptance = ran + session continued.
2. **Ambiguous is never dropped silently**: the headline mean is over decisive
   records (accepted ∪ reverted); the two-sided bound scores every
   grounding-backed record with ambiguous counted both ways.
3. **Shadow counterfactuals**: shadow mode means every logged call executed,
   so grounded outcomes are the realized proceed-world for ALL decisions —
   blocks and asks are scored against what actually happened to the call they
   would have stopped.
4. **Label recovery**: the persisted grounding record stores only
   completed/reverted; accepted-but-errored calls land in ambiguous.
   Hook-only events (result-hook `completed=true` is universal in shadow
   mode) are non-decisive.
5. **Ask scoring** is the flat −q step-table row; ask-resolution scoring
   awaits real ask verdicts (asks never actually asked in shadow mode).
6. **Category** is recomputed with TODAY'S `_block_category` rule over the
   logged decide-time features — not necessarily the rule live at decision
   time (not persisted).
7. **Profile** is assumed default for the incumbent's logged decisions (not
   persisted). The profile sweep re-VALUES decisions; it does not re-decide.
8. **retries** is diagnostic-only (single-digit nonzero counts — no
   statistical power); **spend_usd** substitutes for c in the
   proceed-on-reverted cell when measured (inert while unlogged); **error**
   is unused (folded into completed at grounding time); **latency** is
   telemetry (the step table has no time column — deliberately not yet
   priced).
9. **π\\*** is the per-decision analogue of the INTEGRATED.md break-even:
   π\\* = B / (B + catch·c) with B = FBR·λc + ask-rate·q per wanted decision;
   catch = 0 ⇒ π\\* = ∞ (blocking that never catches waste never pays).
10. **The challenger replay** boots on warm counts only and interleaves
    verdicts at their log positions (no future-evidence leak); outcome
    records are not fed (table@1/epoch-1 has no outcome channel). Scored on
    the event_id intersection when the log grew past the replay's snapshot
    (drift is warned, never silent).
"""


def _f(x: Any, nd: int = 5) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _pct(x: Any) -> str:
    return "—" if x is None else f"{100 * x:.2f}%"


def baseline_table(corpus: dict[str, Any]) -> str:
    labels = ["accepted", "reverted", "ambiguous", "hook-only", "ungrounded"]
    lines = ["| decision | " + " | ".join(labels) + " | total |",
             "|---|" + "---|" * (len(labels) + 1)]
    for action, counts in corpus["per_action"].items():
        row = [str(counts.get(lb, 0)) for lb in labels]
        lines.append(f"| {action} | " + " | ".join(row)
                     + f" | {sum(counts.values())} |")
    return "\n".join(lines)


def engine_table(engines: dict[str, Any]) -> str:
    order = [k for k in ("ORACLE", "UNGOVERNED", "incumbent", "membrane-table@1")
             if k in engines] + [k for k in sorted(engines)
                                 if k not in ("ORACLE", "UNGOVERNED",
                                              "incumbent", "membrane-table@1")]
    lines = ["| engine | mean loss $/decision | bounds (ambiguous both ways) | "
             "FBR (waste) | FBR (safety) | ask-rate on accepted | catch on "
             "reverted | π* break-even |", "|---|---|---|---|---|---|---|---|"]
    for name in order:
        s = engines[name]
        b = s.get("mean_loss_bounds")
        bounds = f"[{_f(b[0])}, {_f(b[1])}]" if b else "—"
        fbr_w = s["fbr_by_category"].get("waste", {}).get("fbr")
        fbr_s = s["fbr_by_category"].get("safety", {}).get("fbr")
        pi = ("∞" if s.get("breakeven_pi_infinite")
              else _f(s.get("breakeven_pi"), 4))
        lines.append(
            f"| {name} | {_f(s['mean_loss'])} | {bounds} | {_pct(fbr_w)} | "
            f"{_pct(fbr_s)} | {_pct(s['ask_rate_on_accepted'])} | "
            f"{_pct(s['catch_on_reverted'])} | {pi} |")
    return "\n".join(lines)


def sweep_table(sweep: dict[str, Any]) -> str:
    engines = sorted(next(iter(sweep.values())).keys())
    lines = ["| profile | " + " | ".join(engines) + " |",
             "|---|" + "---|" * len(engines)]
    for pname, per_engine in sweep.items():
        cells = [_f(per_engine[e]["mean_loss"]) for e in engines]
        lines.append(f"| {pname} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render(results: dict[str, Any]) -> str:
    m = results["manifest"]
    corpus = results["corpus"]
    ch = results.get("challenger")
    parts = [
        "# The outcome-scored governance bench (Phase 1)",
        "",
        "Scores governance decisions against GROUNDED OUTCOMES in the "
        "engine's own step-table currency — the R-D14 candidate metric "
        "replacing retired decision-agreement-%. Registration of the metric "
        "and the bar values is the author's act "
        "(`docs/rd14-registration-draft.md`); this page is the measured "
        "reading. Regenerate: `bench.py` then `report.py` (see module "
        "docstrings).",
        "",
        "## Corpus",
        "",
        f"- snapshot: `{m['path']}` — {m['n_lines']} lines, "
        f"sha256 `{m['sha256'][:16]}…`, read {m['read_at']}",
        f"- joined decisions: **{corpus['decisions']}** "
        f"(orphans: {results['orphans']})",
        f"- would-block rate: **{_pct(corpus['would_block_rate'])}**; "
        f"decisive records (accepted ∪ reverted): **{corpus['decisive']}**; "
        f"reverted: {corpus['reverted_total']}; outcome-justified blocks: "
        f"**{corpus['outcome_justified_blocks']}**",
        "- drift note: the log grows live (the daemon keeps deciding); this "
        "table supersedes the roadmap's 2026-07-10 baseline — same shape, "
        "larger counts.",
        "",
        baseline_table(corpus),
        "",
        "## Engines on the same corpus",
        "",
        engine_table(results["engines"]),
        "",
    ]
    if ch:
        parts += [
            f"- challenger replay: {ch['engine'].get('version')} "
            f"`{ch['engine'].get('utility_form', 'table@1')}` — "
            f"{ch['scored_intersection']} of {corpus['decisions']} decisions "
            f"scored (replay snapshot sha256 `{ch['manifest']['sha256'][:16]}…`"
            f"{'; MANIFEST MISMATCH — intersection scoring' if ch['manifest_mismatch'] else ''})",
            "",
        ]
    bars = results["bars"]
    registered = bars.get("registered", "UNREGISTERED")
    parts += [
        f"## The exit-from-shadow bar (REGISTERED: {registered})",
        "",
        "Enforcement returns per-category only when an engine's false-block "
        "rate on grounded outcomes clears the declared bar with a minimum "
        "evidence floor, over the declared window "
        f"({bars.get('window_days', '?')} days rolling; "
        f"{bars.get('window_note', '')}). The safety category carries NO "
        "declared bar — deferred to the harm-channel ruling (this currency "
        "prices waste only) — so safety rows read —. A clear PERMITS "
        "enforcement in that category; it never compels it (promotion is "
        "Phase 4's separate act). Note the vacuous clear: an engine that "
        "never blocks (the all-ask membrane, UNGOVERNED) clears the "
        "block-FBR bar trivially — clearing says its BLOCKING is "
        "outcome-safe, nothing about its friction.",
        "",
        "| category | bar (FBR ≤) | n_min | " + " | ".join(
            f"{e} clears?" for e in ("incumbent", "membrane-table@1")) + " |",
        "|---|---|---|---|---|",
    ]
    cats = sorted(results["engines"]["incumbent"]["fbr_by_category"])
    for cat in cats:
        bar = bars["values"].get(cat, {}).get("fbr_bar")
        bar_txt = f"{100 * bar:.2f}%" if bar is not None else "— (deferred)"
        cells = []
        for eng in ("incumbent", "membrane-table@1"):
            v = bars["clears"].get(eng, {}).get(cat)
            cells.append("—" if v is None else ("PASS" if v else "FAIL"))
        parts.append(f"| {cat} | {bar_txt} | {bars['n_min']} | "
                     + " | ".join(cells) + " |")
    parts += ["", CAVEATS]
    if "profile_sweep" in results:
        parts += ["## Profile sweep — mean loss $/decision under each buyer "
                  "profile (presets ∪ personas)", "",
                  sweep_table(results["profile_sweep"]), ""]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", default=RESULTS_JSON)
    ap.add_argument("--out", default=OUT_MD)
    args = ap.parse_args(argv)
    with open(args.results, encoding="utf-8") as f:
        results = json.load(f)
    md = render(results)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
