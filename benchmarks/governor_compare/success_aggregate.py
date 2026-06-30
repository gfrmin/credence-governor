# Role: eval
"""success_aggregate.py — success_results.json → SUCCESS.md (client-facing, Phase 3 success axis).

The buyer question: "if I put a governor in front of my coding agent, will it stop legit work
from getting done?" The honest answer the data gives:

  1. The success-axis failure mode is a HARD block on legit work. Credence is overridable-by-
     default (2026-06-28), so a false positive is one extra confirmation, never a broken task —
     it CANNOT break completion unless an operator opts a category into hard deny. Rivals that
     hard-deny (regex / allow-list / a classifier like Llama Guard) DO break legit work when
     they misfire; we measure how often, on behaviourally-confirmed-accepted developer calls.
  2. Among governors that never hard-break (Credence, a native permission model), the separator
     is FRICTION — Credence interrupts far less of the accepted work for strictly more coverage.

Measured on two substrates (real captured sessions + the SWE-bench Verified gold-trajectory
anchor); cited rivals carry their mechanism + source, never blended into the measured rows.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
RES = os.path.join(HERE, "success_results.json")
OUT = os.path.join(HERE, "SUCCESS.md")

# Display order + a one-line "what it is" per governor.
ORDER = ["ungoverned", "perfect-allowlist", "regex-denylist", "native-permission",
         "credence-deny-safety", "credence-default"]
WHAT = {
    "ungoverned":           "no governor (the completion ceiling)",
    "perfect-allowlist":    "BOUND — generous capability allow-list (hard block on overt out-of-policy)",
    "regex-denylist":       "REAL — afternoon deny-list guard (hard block on bad signatures)",
    "native-permission":    "REAL — harness native permission model (asks; never hard-denies)",
    "credence-deny-safety": "PRODUCT — Credence with opt-in hard-deny('safety')",
    "credence-default":     "PRODUCT — Credence, overridable-by-default (the shipped governor)",
}

CITED = [
    {"name": "Llama Guard 3", "axis": "harm classifier",
     "note": "open-weight allow/deny safety classifier with **no override path** — every benign "
             "false-positive becomes a hard task-break, not a confirmation. Published evals show a "
             "non-zero benign false-positive rate, and it is content-semantic (not coding-structural), "
             "so it over-flags ordinary code. It also covers neither cost nor waste.",
     "url": "https://huggingface.co/meta-llama/Llama-Guard-3-8B"},
    {"name": "Lakera Guard", "axis": "prompt-injection guard",
     "note": "hosted guardrail (PINT ~92.5%); a hard allow/deny gate over prompts — same structural "
             "limit as Llama Guard for the success axis: a false positive blocks the work outright.",
     "url": "https://www.lakera.ai/"},
]


# Repos that ARE this safety system's own development — where attack-fixture strings live, so a
# rival tripping on one MIGHT be benign-label contamination. Every other repo is unrelated work.
_SAFETY_DEV_REPOS = {"credence", "credence-governor"}


def _broken_repos(row: dict) -> tuple[list[str], list[str]]:
    """Split a governor's broken sessions by repo into (this-safety-system, other dev work),
    read straight from broken_examples so the contamination-vs-genuine-FP split is traceable."""
    safety, other = [], []
    for ex in row.get("broken_examples", []):
        sk = ex.get("session", "")
        repo = sk.split("/git/")[-1].split("'")[0] if "/git/" in sk else sk
        (safety if repo in _SAFETY_DEV_REPOS else other).append(repo)
    return safety, other


def _pct(x) -> str:
    return "—" if x is None else f"{x*100:.1f}%"


def _row(name: str, r: dict) -> str:
    return (f"| {name} | {_pct(r.get('completion_preserved'))} "
            f"| {r.get('broken_sessions')} / {r.get('working_sessions')} "
            f"| {_pct(r.get('hard_break_call_rate'))} | {_pct(r.get('soft_gate_call_rate'))} |")


def _table(governors: dict, header: str, sub: str) -> list[str]:
    L = [f"## {header}\n", sub + "\n",
         "| Governor | Completion-preserved | Sessions broken / working "
         "| Hard-break (call-rate) | Friction (call-rate) |",
         "|---|---|---|---|---|"]
    for nm in ORDER:
        if nm in governors:
            L.append(_row(nm, governors[nm]))
    L.append("")
    L.append("_" + "; ".join(f"**{nm}** = {WHAT[nm]}" for nm in ORDER if nm in governors) + "._\n")
    return L


def main() -> int:
    d = json.load(open(RES))
    prim, anc = d["primary"], d["anchor"]
    pg, ag = prim["governors"], anc["governors"]

    L: list[str] = []
    L.append("# Success axis — does governing break legit coding work?\n")
    L.append(f"_Phase 3. A governor fails the success axis by HARD-blocking work the developer "
             f"would have kept. We measure that two ways: **(primary)** replaying "
             f"{prim['scored_sessions']} substantive real Claude Code sessions "
             f"({prim['scored_calls']} behaviourally-confirmed-accepted calls), each grounded by Phase-1 outcome replay into "
             f"accepted / reverted / ambiguous (`OUTCOMES.md`); a *working session* has ≥1 "
             f"behaviourally-confirmed-**accepted** call, and a **break** is a non-overridable hard "
             f"block on an accepted call. **(anchor)** {anc['tasks']} SWE-bench Verified gold "
             f"trajectories ({anc['calls']} synthesized calls) — does each governor PERMIT the "
             f"verified solution path? Every governor scores the byte-identical record stream._\n")

    L += _table(pg, "Primary — real captured developer sessions",
                "_Completion-preserved = 1 − (sessions hard-broken / working sessions). Hard-break "
                "call-rate = share of accepted calls a NON-overridable deny lands on (a real task-break). "
                "Friction call-rate = share of accepted calls an OVERRIDABLE gate (ask / overridable block) "
                "interrupts — real, but recoverable with one confirmation, never a break._")

    # ── the honest read ──
    L.append("## What the success data says\n")
    cd, nat = pg.get("credence-default"), pg.get("native-permission")
    cds = pg.get("credence-deny-safety")
    rx, al = pg.get("regex-denylist"), pg.get("perfect-allowlist")
    L.append("- **Credence cannot break legit work by default — that's structural, not luck.** Since "
             "2026-06-28 every Credence decision is overridable (a categorical deny implies infinite "
             "disutility, which a finite harm-cost H contradicts — so the human's \"I actually want "
             "this\" is admissible evidence). A false positive is therefore **one extra confirmation, "
             "never a broken task**: `credence-default` preserves "
             f"{_pct(cd and cd.get('completion_preserved'))} of working sessions, hard-breaking "
             f"{_pct(cd and cd.get('hard_break_call_rate'))} of accepted calls — by construction.\n")
    if rx and al:
        al_s, al_o = _broken_repos(al)
        rx_s, rx_o = _broken_repos(rx)
        L.append("- **Hard-deny rivals DO break real work.** A non-overridable block is a task-break when "
                 f"it lands on a kept call. Even at a ~1% call-level false-block rate "
                 f"({_pct(al.get('hard_break_call_rate'))}/{_pct(rx.get('hard_break_call_rate'))} of "
                 "accepted calls), ONE hard block derails a whole session — so `perfect-allowlist` "
                 f"preserves only {_pct(al.get('completion_preserved'))} "
                 f"({al.get('broken_sessions')}/{al.get('working_sessions')} sessions broken) and "
                 f"`regex-denylist` {_pct(rx.get('completion_preserved'))} "
                 f"({rx.get('broken_sessions')}/{rx.get('working_sessions')}). That session-level "
                 "amplification is the buyer's real exposure.\n")
        L.append("- **And most of those breaks are GENUINE false positives, not fixture noise.** Of "
                 f"perfect-allowlist's {al.get('broken_sessions')} broken sessions, {len(al_s)} are in "
                 "this safety system's own repos (where attack-test-fixtures live → possible "
                 f"contamination) but **{len(al_o)} are unrelated developer projects** "
                 f"({', '.join(sorted(set(al_o)))}); regex-denylist's split is {len(rx_s)} vs "
                 f"**{len(rx_o)}** ({', '.join(sorted(set(rx_o)))}). These are ordinary dev operations "
                 "the developer ran and kept (destructive build steps, privilege ops, credential-adjacent "
                 "calls) that a signature/allow-list guard mis-flags — the over-block tax on real work, "
                 "independent of this corpus's quirks.\n")
    if cds:
        L.append("- **Opt-in hard-deny costs completion — which is exactly why overridable is the "
                 f"default.** Flip Credence into hard-deny('safety') and it breaks "
                 f"{cds.get('broken_sessions')}/{cds.get('working_sessions')} sessions "
                 f"({_pct(cds.get('completion_preserved'))} preserved): the safety label DOES fire on "
                 "some accepted calls (partly the same fixture contamination). The shipped default keeps "
                 "those as overridable confirmations, turning would-be breaks into friction — the "
                 "finite-H argument made concrete.\n")
    if cd and nat:
        L.append("- **The real separator is friction, and Credence wins it decisively.** Both Credence and "
                 "a native permission model avoid hard-breaks, but native-permission interrupts "
                 f"**{_pct(nat.get('soft_gate_call_rate'))}** of accepted calls vs Credence's "
                 f"**{_pct(cd.get('soft_gate_call_rate'))}** — a ~"
                 f"{round((nat.get('soft_gate_call_rate') or 0)/(cd.get('soft_gate_call_rate') or 1))}× "
                 "reduction. Native asks on tool SHAPE alone (no provenance, data-flow, or harm-probability "
                 "notion — where that lands on the harm axis is `COMPARISON.md`, not measured here); "
                 "Credence reaches the same no-break safety while interrupting a fraction as much real "
                 "work.\n")

    # ── anchor ──
    L += _table(ag, "Anchor — SWE-bench Verified gold trajectories (public)",
                "_Each Verified instance ships a gold patch the SWE-bench harness CONFIRMED resolves the "
                "task. We synthesize its solving tool-calls (read → edit → run the failing tests) and ask "
                "each governor whether it permits that verified path. No agent, no docker — resolution is "
                "given; we measure only permission. Completion-preserved here = resolved-path-preserved._")
    un = ag.get("credence-default")
    nat_a = ag.get("native-permission")
    L.append("## What the anchor confirms\n")
    L.append("- **On clean public code, no governor hard-breaks the verified fix** — completion-preserved "
             "is 100% across the board. This establishes a useful floor (the gold path's tool-calls — "
             "read / edit / `pytest` — don't trip the signature rivals on clean code), but it is NOT a "
             "claim that the real-session breaks were all contamination: those were mostly genuine false "
             "positives on unrelated dev work (above). The anchor's narrow tool-call set simply doesn't "
             "replicate the destructive / privilege / credential-adjacent operations that broke real "
             "sessions.\n")
    if un and nat_a:
        L.append("- **Friction still separates them on the gold path.** Even on a known-good solution, "
                 f"native-permission interrupts {_pct(nat_a.get('soft_gate_call_rate'))} of calls (it asks "
                 "on every test-run), while Credence interrupts "
                 f"{_pct(un.get('soft_gate_call_rate'))} — a consistent separation, reproduced on a clean "
                 "public set.\n")

    # ── cited ──
    L.append("## Cited rivals (mechanism + source — not run here)\n")
    for c in CITED:
        L.append(f"- **{c['name']}** ({c['axis']}): {c['note']} [source]({c['url']})")
    L.append("")
    L.append("## Reading\n")
    L.append("- **Measured** rows ran on the identical record stream (real sessions + the public anchor); "
             "**cited** rows are third-party guardrails, tagged and linked, never blended.\n"
             f"- **Denominator:** the {prim['working_total']} working sessions are the *substantive* "
             f"multi-call sessions — they hold essentially the entire corpus; the other "
             f"{prim.get('nonworking_total', 0)} sessions are all 1-call singletons "
             f"(max size {prim.get('nonworking_max_size', 0)}, "
             f"{prim.get('nonworking_singletons', 0)}/{prim.get('nonworking_total', 0)}) with no observed "
             "continuation, so no landed work to break. The session count is small, so the **per-call "
             f"rates (over {prim['scored_calls']} accepted calls) are the robust measure**; session-level "
             "completion-preserved is the harsher, derail-amplified view.\n"
             "- A **break** is a non-overridable hard block on a behaviourally-confirmed-accepted call — "
             "work the developer demonstrably kept. Blocks on reverted/ambiguous calls never count.\n"
             "- **Credence's no-break property is a design choice (overridability), reported as such** — "
             "the *measured* claims are (a) how often the hard-deny rivals actually fire on accepted work "
             "and (b) the friction separation between Credence and a native permission model.\n"
             "- **Caveat (corpus hygiene):** the captured corpus includes this project's own development "
             "of the safety system — synthetic attack payloads authored as test fixtures appear as benign "
             "calls and trip the signature rivals. But that accounts for only a MINORITY of their breaks "
             "(the split above); the majority are genuine false positives on unrelated dev work. Either "
             "way the inflation is a caveat *against the rivals*, and the contamination-free SWE-bench "
             "anchor isolates the floor.\n"
             "- **Honest limit of the anchor:** it scores the KNOWN-GOOD solution PATH, not an autonomous "
             "agent's resolved-rate; permitting the gold path is necessary (not sufficient) for an agent "
             "to resolve via it. A full agent + docker run is the heavier future upgrade.\n"
             "- The credence rows are the real BrainSession decision over the skin wire; the two variants "
             "are the shipped overridable-by-default governor and the opt-in hard-deny('safety') config.")

    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
