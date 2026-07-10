"""replay.py — the challenger replay: every logged decision context, in
arrival order, through a fresh warm-booted **table@1** MembraneSession
(the non-degenerate proplang policy; the latent@1 generation is the
Phase-2 live shadow's falsification instrument, not this bench's
challenger).

Causality: the session boots on an EMPTY temp log (warm counts only) —
bulk-replaying the observation log at boot would leak future evidence into
early decisions. Instead the replay interleaves each `user-responded`
verdict at its log position between decides, mirroring what deployment
would have fed. Outcome records are NOT fed: table@1/epoch-1 has no
outcome evidence channel.

Output: challenger_decisions.json {manifest, engine, decisions, ticks,
wall_clock_s} — the cache that makes scoring re-runnable without the
~hour-scale replay. --verify re-replays and diffs against the committed
file (the determinism witness: the engine is argmax-EU with a first-listed
tie-break over a declared evidence stream).

Run (the govhost binary is env-selected, executed read-only):
    CREDENCE_MEMBRANE_COMMAND=~/.local/bin/proplang-govhost \\
    uv run --project packages/governor_core python benchmarks/outcome_bench/replay.py
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from typing import Any, Callable

from credence_governor_core.daemon import data_dir
from credence_governor_core.log import ObservationLog
from credence_governor_core.membrane import build_membrane_session

import corpus

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "challenger_decisions.json")


def replay_decisions(records: list[dict[str, Any]], session: Any,
                     progress: Callable[[int, int], None] | None = None,
                     ) -> dict[str, str]:
    """One chronological pass: tool-proposed → decide (keyed by event_id);
    user-responded yes/no → observe at its log position. Everything else
    (outcome, membrane-shadow, route-*, telemetry) is inert here."""
    decisions: dict[str, str] = {}
    feats_by_id: dict[str, dict[str, str]] = {}
    n = len(records)
    for i, r in enumerate(records):
        et = r.get("event_type")
        if et == "tool-proposed" and isinstance(r.get("event_id"), str) and r.get("features"):
            feats_by_id[r["event_id"]] = r["features"]
            decisions[r["event_id"]] = session.decide(r["features"])
        elif et == "user-responded":
            feats = feats_by_id.get(str(r.get("in_response_to")))
            resp = str(r.get("response") or "")
            if feats and resp in ("yes", "no"):
                session.observe(feats, 1 if resp == "yes" else 0)
        if progress is not None and i % 2000 == 0:
            progress(i, n)
    return decisions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=corpus.DEFAULT_LOG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0,
                    help="replay only the first N records (0 = all)")
    ap.add_argument("--verify", action="store_true",
                    help="re-replay and diff against the committed --out file")
    args = ap.parse_args(argv)

    records, manifest = corpus.read_snapshot(args.log)
    if args.limit:
        records = records[: args.limit]
        manifest["limited_to"] = args.limit

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        empty_log = ObservationLog(os.path.join(tmp, "empty.jsonl"))
        session = build_membrane_session(
            os.path.join(data_dir(), "brain"), empty_log,
            logline=lambda m: print(m, flush=True))
        try:
            session.boot()   # warm counts only — the empty log adds nothing
            decisions = replay_decisions(
                records, session,
                progress=lambda i, n: print(f"replay {i}/{n}", flush=True))
        finally:
            session.client.shutdown()
    wall = round(time.monotonic() - t0, 1)

    payload = {
        "manifest": manifest,
        "engine": dict(session.engine or {}),
        "ticks": len(decisions),
        "wall_clock_s": wall,
        "decisions": decisions,
    }

    if args.verify:
        with open(args.out, encoding="utf-8") as f:
            committed = json.load(f)
        same = committed["decisions"] == decisions
        print(f"verify: {'IDENTICAL' if same else 'DIVERGED'} "
              f"({len(decisions)} decisions, {wall}s)")
        return 0 if same else 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {args.out}: {len(decisions)} decisions in {wall}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
