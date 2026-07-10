"""bench.py — score governance engines against grounded outcomes in the
engine's own step-table currency (governance-roadmap Phase 1; the R-D14
candidate metric). Replaces retired decision-agreement-%.

Engines scored on the SAME BenchRecord corpus:
  - incumbent: the LOGGED shadow decisions (free — shadow mode means every
    logged decision has a realized proceed-world outcome);
  - challenger: `challenger_decisions.json` (the table@1 membrane replay);
  - UNGOVERNED (always proceed) and ORACLE (proceed on accepted, block on
    reverted) — the floor and ceiling that make the table legible.

The headline is mean realized loss per DECISIVE decision (accepted ∪
reverted), with a two-sided bound over the grounding-backed population
(ambiguous scored both ways — never silently dropped). Exit-from-shadow
ships as a SHAPE: `clears_bar(score, bars, n_min)`; the numeric bars are
author-declared placeholders (registration is the author's act,
docs/rd14-registration-draft.md).

Run:
    uv run --project packages/governor_core python benchmarks/outcome_bench/bench.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "approach_dominance"))

from credence_governor_core.config import UTILITY

import corpus
from join import BenchRecord, corpus_stats, join
from loss import GROUNDED, DECISIVE, loss_bounds, realized_loss

HERE = os.path.dirname(os.path.abspath(__file__))
CHALLENGER_JSON = os.path.join(HERE, "challenger_decisions.json")
RESULTS_JSON = os.path.join(HERE, "outcome_bench_results.json")


@dataclass(frozen=True)
class EngineScore:
    n_scoreable: int                    # decisions this engine made on the corpus
    n_decisive: int
    mean_loss: float | None             # $/decision over decisive records
    mean_loss_bounds: tuple[float, float] | None   # ambiguous scored both ways
    n_bounded: int                      # the grounding-backed population
    fbr_by_category: dict[str, dict[str, Any]]
    ask_rate_on_accepted: float | None
    catch_on_reverted: float | None
    breakeven_pi: float | None          # inf serialized as None-with-flag below
    measured_pi: float | None
    actions: dict[str, int] = field(default_factory=dict)


def _profile_dict(profile: Any | None) -> dict[str, float] | None:
    """A benchmarks/approach_dominance Profile → the engine's profile dict
    (utility_rows keys). The call-cost c has no Profile dial and stays the
    engine's declared UTILITY['cost']."""
    if profile is None:
        return None
    return {"aversion": profile.lam, "interrupt_cost": profile.q,
            "harm_cost": profile.harm}


def score_engine(rows: list[BenchRecord], decisions: Mapping[str, str],
                 profile: Any | None = None) -> EngineScore:
    pdict = _profile_dict(profile)
    c = float(UTILITY["cost"])
    lam = profile.lam if profile is not None else float(UTILITY["aversion"])
    q = profile.q if profile is not None else float(UTILITY["interrupt_cost"])

    losses: list[float] = []
    lo_sum = hi_sum = 0.0
    n_bounded = 0
    accepted_by_cat: dict[str, int] = {}
    blocks_on_accepted_by_cat: dict[str, int] = {}
    blocks_by_cat: dict[str, int] = {}
    asks_on_accepted = 0
    accepted_total = 0
    reverted_total = 0
    blocks_on_reverted = 0
    actions: dict[str, int] = {}
    n_scoreable = 0

    for r in rows:
        action = decisions.get(r.event_id)
        if action is None:
            continue
        n_scoreable += 1
        actions[action] = actions.get(action, 0) + 1
        label = r.outcome.label
        x = realized_loss(action, label, pdict, spend_usd=r.outcome.spend_usd)
        if x is not None:
            losses.append(x)
        if label in GROUNDED:
            lo, hi = loss_bounds(action, label, pdict,
                                 spend_usd=r.outcome.spend_usd)
            lo_sum += lo
            hi_sum += hi
            n_bounded += 1
        if label == "accepted":
            accepted_total += 1
            accepted_by_cat[r.category] = accepted_by_cat.get(r.category, 0) + 1
            if action == "block":
                blocks_on_accepted_by_cat[r.category] = (
                    blocks_on_accepted_by_cat.get(r.category, 0) + 1)
            if action == "ask":
                asks_on_accepted += 1
        elif label == "reverted":
            reverted_total += 1
            if action == "block":
                blocks_on_reverted += 1
        if action == "block":
            blocks_by_cat[r.category] = blocks_by_cat.get(r.category, 0) + 1

    fbr_by_category: dict[str, dict[str, Any]] = {}
    for cat in sorted(set(accepted_by_cat) | set(blocks_by_cat)):
        n_acc = accepted_by_cat.get(cat, 0)
        boa = blocks_on_accepted_by_cat.get(cat, 0)
        n_blk = blocks_by_cat.get(cat, 0)
        fbr_by_category[cat] = {
            # FBR: what fraction of confirmed-good work enforcement would destroy
            "fbr": boa / n_acc if n_acc else None,
            # precision variant: what share of this category's blocks hit good work
            "blocks_on_accepted_share": boa / n_blk if n_blk else None,
            "n_accepted": n_acc,
            "blocks_on_accepted": boa,
            "blocks": n_blk,
        }

    fbr_overall = (
        sum(blocks_on_accepted_by_cat.values()) / accepted_total
        if accepted_total else None)
    ask_rate = asks_on_accepted / accepted_total if accepted_total else None
    catch = blocks_on_reverted / reverted_total if reverted_total else None
    decisive_total = accepted_total + reverted_total

    # π*: the wasteful-call base-rate above which this engine's blocking pays
    # for its friction — the per-decision analogue of integrate.breakeven_pi,
    # with the wasted-call price c in the harm slot. B = expected $-overhead
    # per WANTED decision (false blocks at λc + asks at q).
    breakeven: float | None = None
    if fbr_overall is not None and ask_rate is not None and catch is not None:
        B = fbr_overall * lam * c + ask_rate * q
        breakeven = math.inf if catch <= 0 and B > 0 else (
            0.0 if catch <= 0 else B / (B + catch * c))

    return EngineScore(
        n_scoreable=n_scoreable,
        n_decisive=len(losses),
        mean_loss=sum(losses) / len(losses) if losses else None,
        mean_loss_bounds=(
            (lo_sum / n_bounded, hi_sum / n_bounded) if n_bounded else None),
        n_bounded=n_bounded,
        fbr_by_category=fbr_by_category,
        ask_rate_on_accepted=ask_rate,
        catch_on_reverted=catch,
        breakeven_pi=breakeven,
        measured_pi=(reverted_total / decisive_total if decisive_total else None),
        actions=actions,
    )


def clears_bar(score: EngineScore, bars: Mapping[str, Mapping[str, float]],
               n_min: int) -> dict[str, bool | None]:
    """The exit-from-shadow SHAPE (values are the author's to declare):
    per category k, clears ⇔ FBR_k ≤ bar_k AND n_accepted_k ≥ n_min.
    None = insufficient evidence (a category may not clear on a tiny
    denominator) or no declared bar."""
    out: dict[str, bool | None] = {}
    for cat, stats in score.fbr_by_category.items():
        bar = bars.get(cat, {}).get("fbr_bar")
        if bar is None or stats["n_accepted"] < n_min or stats["fbr"] is None:
            out[cat] = None
        else:
            out[cat] = stats["fbr"] <= bar
    return out


def oracle_decisions(rows: list[BenchRecord]) -> dict[str, str]:
    """The hindsight ceiling: proceed on accepted, block on reverted;
    proceed elsewhere (non-decisive records cost either way)."""
    return {
        r.event_id: "block" if r.outcome.label == "reverted" else "proceed"
        for r in rows
    }


def _score_to_json(s: EngineScore) -> dict[str, Any]:
    d = asdict(s)
    if d["breakeven_pi"] is not None and math.isinf(d["breakeven_pi"]):
        d["breakeven_pi"] = None
        d["breakeven_pi_infinite"] = True
    return d


def profile_sweep(rows: list[BenchRecord],
                  engines: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    from profiles import PERSONAS, PRESETS  # noqa: PLC0415 — sys.path set above
    sweep: dict[str, Any] = {}
    for pname, prof in {**PRESETS, **PERSONAS}.items():
        sweep[pname] = {
            engine: _score_to_json(score_engine(rows, dec, prof))
            for engine, dec in engines.items()
        }
    return sweep


# The declared bars — REGISTERED at the author's R-D14 boundary (proplang
# tag rd14-close, 2026-07-11): bar_waste = 0.05% (at-or-under the
# perfect-catch break-even at the measured base rate), n_min = 1,000
# accepted per category, window = rolling 30 days. The safety category's
# bar is DEFERRED to the harm-channel ruling (this currency prices waste
# only), so safety carries no declared bar and clears_bar returns None.
REGISTERED_BARS: dict[str, dict[str, float]] = {
    "waste": {"fbr_bar": 0.0005},
}
REGISTERED_N_MIN = 1000
REGISTERED_WINDOW_DAYS = 30
REGISTRATION = "proplang tag rd14-close (2026-07-11)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=corpus.DEFAULT_LOG)
    ap.add_argument("--challenger", default=CHALLENGER_JSON)
    ap.add_argument("--out", default=RESULTS_JSON)
    ap.add_argument("--stats-only", action="store_true")
    ap.add_argument("--no-sweep", action="store_true")
    args = ap.parse_args(argv)

    records, manifest = corpus.read_snapshot(args.log)
    rows, orphans = join(records)
    # the REGISTERED window (rolling 30 days): rows whose decision carries a
    # ts older than the window are excluded; unstamped rows (the pre-ts
    # corpus) are included — every one predates the ts field (2026-07-11)
    # and the capture itself is younger than the window, so inclusion is
    # exact today and the roll becomes exact as stamped records accumulate.
    read_epoch = time.mktime(time.strptime(manifest["read_at"], "%Y-%m-%dT%H:%M:%SZ"))
    cutoff = read_epoch - REGISTERED_WINDOW_DAYS * 86400
    n_before = len(rows)
    rows = [r for r in rows if r.ts is None or r.ts >= cutoff]
    window_note = (f"rolling {REGISTERED_WINDOW_DAYS}d: {n_before - len(rows)} "
                   f"stamped rows aged out; unstamped rows included (pre-ts corpus)")
    stats = corpus_stats(rows)
    print(json.dumps({"manifest": manifest, "orphans": orphans,
                      "corpus": stats}, indent=1))
    if args.stats_only:
        return 0

    engines: dict[str, Mapping[str, str]] = {
        "incumbent": {r.event_id: r.action for r in rows},
        "UNGOVERNED": {r.event_id: "proceed" for r in rows},
        "ORACLE": oracle_decisions(rows),
    }
    challenger_note: dict[str, Any] | None = None
    if os.path.exists(args.challenger):
        with open(args.challenger, encoding="utf-8") as f:
            ch = json.load(f)
        engines["membrane-table@1"] = ch["decisions"]
        challenger_note = {
            "manifest": ch["manifest"],
            "engine": ch.get("engine"),
            "manifest_mismatch": ch["manifest"]["sha256"] != manifest["sha256"],
            "scored_intersection": sum(
                1 for r in rows if r.event_id in ch["decisions"]),
        }
        if challenger_note["manifest_mismatch"]:
            print("WARNING: challenger replay manifest != this corpus snapshot "
                  "(the log grew); scoring the event_id intersection.")

    results = {
        "manifest": manifest,
        "orphans": orphans,
        "corpus": stats,
        "challenger": challenger_note,
        "engines": {name: _score_to_json(score_engine(rows, dec))
                    for name, dec in engines.items()},
        "bars": {"values": REGISTERED_BARS,
                 "n_min": REGISTERED_N_MIN,
                 "window_days": REGISTERED_WINDOW_DAYS,
                 "window_note": window_note,
                 "registered": REGISTRATION,
                 "clears": {
                     name: clears_bar(score_engine(rows, dec),
                                      REGISTERED_BARS, REGISTERED_N_MIN)
                     for name, dec in engines.items()}},
    }
    if not args.no_sweep:
        results["profile_sweep"] = profile_sweep(rows, engines)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {args.out}")
    for name in engines:
        s = results["engines"][name]
        print(f"  {name:18s} mean_loss/decision "
              f"{s['mean_loss'] if s['mean_loss'] is None else round(s['mean_loss'], 5)} "
              f"bounds {s['mean_loss_bounds']} catch {s['catch_on_reverted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
