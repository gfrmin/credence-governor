"""join.py — the 3-way observation-log join (tool-proposed × decision ×
outcome, keyed on event_id/in_response_to) and the corpus statistics that
reproduce/supersede the governance-roadmap baseline table. Pure over a
record list — corpus.py does the one file read.

Category is recomputed offline from the logged decide-time features via
`daemon._block_category` (deterministic feature inspection; verified to run
on every historical feature keyset — older records simply leave the coding
rules inert). Registered caveat: this is TODAY'S rule, not necessarily the
rule live at decision time.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from credence_governor_core.daemon import _block_category

from loss import DECISIVE, GroundedOutcome, merge_outcomes


@dataclass(frozen=True)
class BenchRecord:
    event_id: str
    log_index: int              # the tool-proposed record's arrival position
    ts: float | None            # decide-time epoch seconds (None: pre-ts corpus)
    features: dict[str, str]
    action: str                 # the LOGGED (incumbent, shadow-mode) decision
    outcome: GroundedOutcome
    category: str               # _block_category(features), recomputed


def join(records: list[dict[str, Any]]) -> tuple[list[BenchRecord], dict[str, int]]:
    """BenchRecords in arrival order, plus orphan counts: decisions without
    a proposal, outcomes without a proposal, proposals without a decision."""
    proposed: dict[str, tuple[int, dict[str, str], float | None]] = {}
    for i, r in enumerate(records):
        if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str) and r.get("features"):
            ts = r.get("ts")
            proposed[r["event_id"]] = (
                i, r["features"], float(ts) if isinstance(ts, (int, float)) else None)
    actions: dict[str, str] = {}
    orphan_decisions = 0
    outcomes: dict[str, list[dict[str, Any]]] = {}
    orphan_outcomes = 0
    for r in records:
        et = r.get("event_type")
        eid = str(r.get("in_response_to") or "")
        if et == "decision":
            if eid in proposed:
                actions[eid] = str(r.get("action"))
            else:
                orphan_decisions += 1
        elif et == "outcome":
            if eid in proposed:
                outcomes.setdefault(eid, []).append(r)
            else:
                orphan_outcomes += 1
    rows: list[BenchRecord] = []
    undecided = 0
    for eid, (idx, feats, ts) in proposed.items():
        action = actions.get(eid)
        if action is None:
            undecided += 1
            continue
        rows.append(BenchRecord(
            event_id=eid,
            log_index=idx,
            ts=ts,
            features=feats,
            action=action,
            outcome=merge_outcomes(outcomes.get(eid, [])),
            category=_block_category(feats),
        ))
    rows.sort(key=lambda r: r.log_index)
    orphans = {
        "decisions_without_proposal": orphan_decisions,
        "outcomes_without_proposal": orphan_outcomes,
        "proposals_without_decision": undecided,
    }
    return rows, orphans


def corpus_stats(rows: list[BenchRecord]) -> dict[str, Any]:
    """The baseline table (the roadmap's shape, recomputed): per action ×
    label, the would-block rate, the per-category split, and the
    outcome-justified-block count."""
    by_action: dict[str, Counter] = {}
    by_category: dict[str, Counter] = {}
    for r in rows:
        by_action.setdefault(r.action, Counter())[r.outcome.label] += 1
        by_category.setdefault(r.category, Counter())[r.action] += 1
    total = len(rows)
    blocks = sum(sum(c.values()) for a, c in by_action.items() if a == "block")
    decisive = sum(
        c[label] for c in by_action.values() for label in DECISIVE)
    return {
        "decisions": total,
        "per_action": {a: dict(c) for a, c in sorted(by_action.items())},
        "per_category_actions": {k: dict(c) for k, c in sorted(by_category.items())},
        "would_block_rate": blocks / total if total else None,
        "decisive": decisive,
        "outcome_justified_blocks": by_action.get("block", Counter())["reverted"],
        "reverted_total": sum(c["reverted"] for c in by_action.values()),
    }
