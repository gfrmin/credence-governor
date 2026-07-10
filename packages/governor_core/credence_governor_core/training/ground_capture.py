"""ground_capture.py — post-hoc grounding: backfill MEASURED outcomes for gated calls.

The result-time hook records what a call did as it finished (completed, latency). This CLI
grounds the SAME gated calls STRUCTURALLY, after the fact, from the raw capture the daemon
kept: it replays each session's tool_call/tool_result spine (no LLM, no trust in any logged
decision) to read whether the developer kept the call, undid it, or retried it.

For every gated `event_id` in the observation log (a tool-proposed record), we locate the
matching capture record by event_id, classify its fate (accepted / reverted / ambiguous via
credence_governor_core.training.outcomes), and append an `outcome` record:

    {event_type: outcome, in_response_to: <event_id>, source: "grounding",
     reverted: <bool>, completed: <bool>, retries: <int>, latency_s/spend_usd/error: None}

  * reverted  — a later action explicitly undid the call (label == "reverted").
  * completed — the call was located running AND the session continued past it AND its
                tool_result showed no error (executed and continued and not errored).
  * retries   — a documented heuristic: the number of LATER tool_calls in the same session
                that repeat this exact (tool_name, input) AFTER it errored (0 if it did not
                error or could not be located). It counts re-proposals of an identical call,
                a proxy for "the agent tried again"; it is deliberately strict (exact input
                match) so it under-counts rather than over-counts.

Idempotent / incremental: an event_id that already carries a source:"grounding" outcome is
skipped, so re-running only grounds new calls. Outcomes are append-only telemetry, replayed
by nothing — safe to add to a live log. Exit 0 with a printed tally.

    uv run --project packages/governor_core python -m \\
      credence_governor_core.training.ground_capture \\
      --capture ~/.credence-governor/raw_events.jsonl \\
      --log     ~/.credence-governor/observations.jsonl
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Any

from ..log import ObservationLog
from .outcomes import SessionIndex, _canon, _raw_records

DEFAULT_CAPTURE = os.path.expanduser("~/.credence-governor/raw_events.jsonl")
DEFAULT_LOG = os.path.expanduser("~/.credence-governor/observations.jsonl")


def _event_id_index(capture_path: str) -> dict[str, int]:
    """event_id -> cap-{i} index, first-wins (matching _raw_records' dedup, so it aligns with
    SessionIndex's own indexing)."""
    out: dict[str, int] = {}
    for i, rec in _raw_records(capture_path):
        eid = rec.get("event_id")
        if isinstance(eid, str) and eid not in out:
            out[eid] = i
    return out


def _retries_after(si: SessionIndex, idx: int, errored: bool) -> int:
    """Count later tool_calls in the same session repeating this exact (tool_name, input)
    after the call — a retry proxy, only when the call errored. 0 if it did not error or its
    position cannot be located in the session's full transcript."""
    if not errored:
        return 0
    call = si.calls.get(idx)
    if call is None:
        return 0
    key, prefix_len, event = call["key"], call["prefix_len"], call["event"]
    final = si.final_msgs.get(key) or []
    if len(final) <= prefix_len:
        return 0
    tail = final[prefix_len:]
    want = _canon(event["input"])
    pos = next(
        (k for k, m in enumerate(tail)
         if m.get("role") == "tool_call"
         and m.get("tool_name") == event["tool_name"]
         and _canon(m.get("input")) == want),
        None,
    )
    if pos is None:
        return 0
    after = tail[pos + 1:]
    return sum(
        1 for m in after
        if m.get("role") == "tool_call"
        and m.get("tool_name") == event["tool_name"]
        and _canon(m.get("input")) == want
    )


def _grounding_record(event_id: str, si: SessionIndex, idx: int, o: Any) -> dict[str, Any]:
    """The outcome record for one grounded call (given its already-computed classification) —
    measured structural observables only, never a good/bad judgement."""
    return {
        "event_type": "outcome",
        "in_response_to": event_id,
        "source": "grounding",
        "completed": bool(o.executed and o.continued and not o.errored),
        "latency_s": None,
        "spend_usd": None,
        "reverted": o.label == "reverted",
        "retries": _retries_after(si, idx, o.errored),
        "error": None,
    }


def ground(capture_path: str, log_path: str, dry_run: bool = False) -> Counter:
    """Ground every not-yet-grounded gated call in the log against the capture. Returns a
    tally Counter (accepted/reverted/ambiguous/skipped/unmatched)."""
    si = SessionIndex.build(capture_path)
    eid_to_idx = _event_id_index(capture_path)
    log = ObservationLog(log_path)
    records = log.read()

    already_grounded = {
        str(r.get("in_response_to"))
        for r in records
        if r.get("event_type") == "outcome" and r.get("source") == "grounding" and r.get("in_response_to")
    }
    gated = [
        r["event_id"] for r in records
        if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str)
    ]

    tally: Counter = Counter()
    for event_id in gated:
        if event_id in already_grounded:
            tally["skipped"] += 1
            continue
        idx = eid_to_idx.get(event_id)
        if idx is None:
            tally["unmatched"] += 1  # gated but not present in the capture (capture disabled then?)
            continue
        o = si.classify(idx)
        tally[o.label] += 1
        if not dry_run:
            log.append(_grounding_record(event_id, si, idx, o))
    return tally


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill structural outcome records for gated calls.")
    ap.add_argument("--capture", default=DEFAULT_CAPTURE, help="raw capture JSONL (daemon's raw_events.jsonl)")
    ap.add_argument("--log", default=DEFAULT_LOG, help="observation log JSONL to read gated calls from + append outcomes to")
    ap.add_argument("--dry-run", action="store_true", help="classify + tally but append nothing")
    args = ap.parse_args(argv)

    tally = ground(args.capture, args.log, dry_run=args.dry_run)
    verb = "would ground" if args.dry_run else "grounded"
    print(
        f"{verb}: accepted={tally.get('accepted', 0)} reverted={tally.get('reverted', 0)} "
        f"ambiguous={tally.get('ambiguous', 0)}  (skipped={tally.get('skipped', 0)} "
        f"already-grounded, unmatched={tally.get('unmatched', 0)} not-in-capture)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
