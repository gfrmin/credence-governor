"""loss.py — the per-record Wald scorer: (decision × grounded outcome) →
realized loss in the engine's OWN step-table units (governance-roadmap
Phase 1; the R-D14 metric's pure core).

The currency is `membrane.utility_rows` — the same step table the engine
maximises against, indexed rather than re-derived so profile sweeps and any
constant change flow through automatically. Column convention (verified,
pinned by test): **column 0 = the realized-WASTEFUL state (reverted),
column 1 = the realized-WANTED state (accepted)** — so block-on-accepted
costs λc, proceed-on-reverted costs c, ask costs q in either state.

Labels come from the persisted outcome records. The grounding source is
authoritative for acceptance (it alone sees session continuation); in
shadow mode a result-hook's completed=true is universal (everything
executed) and carries zero acceptance information, so hook-only events are
non-decisive. Ambiguous is never dropped silently: `loss_bounds` scores it
both ways, and the headline mean carries a two-sided bound.

Pure module: no I/O, no engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from credence_governor_core.membrane import utility_rows

Label = Literal["accepted", "reverted", "ambiguous", "hook-only", "ungrounded"]

ACTION_TO_FIRE = {"ask": 3, "block": 2, "proceed": 1}
# step-table column per realized state (the verified convention)
_STATE_COL = {"reverted": 0, "accepted": 1}
DECISIVE: tuple[Label, ...] = ("accepted", "reverted")
# labels that carry a grounding record (the bounds population): decisive plus
# the classifier's honest can't-tell bucket
GROUNDED: tuple[Label, ...] = ("accepted", "reverted", "ambiguous")


@dataclass(frozen=True)
class GroundedOutcome:
    label: Label
    reverted: bool
    completed: bool
    retries: int
    spend_usd: float | None
    latency_s: float | None
    sources: tuple[str, ...]


UNGROUNDED = GroundedOutcome(
    label="ungrounded", reverted=False, completed=False, retries=0,
    spend_usd=None, latency_s=None, sources=())


def _label_from_record(rec: dict[str, Any]) -> Label:
    """The persisted-schema label recovery (ground_capture stores only the
    two booleans): reverted → reverted; completed → accepted; else
    ambiguous. Caveat (registered): accepted-but-errored calls were folded
    into completed=False at grounding time and land in ambiguous here."""
    if rec.get("reverted") is True:
        return "reverted"
    if rec.get("completed") is True:
        return "accepted"
    return "ambiguous"


def merge_outcomes(outcome_records: list[dict[str, Any]]) -> GroundedOutcome:
    """One GroundedOutcome per event from its (possibly several) outcome
    records. The label and retries come from the LAST grounding record
    (authoritative — precedence registered); openclaw and result-hook
    records contribute telemetry only (latency/spend, last non-null wins)
    and, absent any grounding record, the non-decisive 'hook-only' label."""
    if not outcome_records:
        return UNGROUNDED
    grounding = [r for r in outcome_records if r.get("source") == "grounding"]
    label: Label = _label_from_record(grounding[-1]) if grounding else "hook-only"
    retries = 0
    if grounding and isinstance(grounding[-1].get("retries"), int):
        retries = grounding[-1]["retries"]
    spend = latency = None
    for r in outcome_records:
        if isinstance(r.get("spend_usd"), (int, float)):
            spend = float(r["spend_usd"])
        if isinstance(r.get("latency_s"), (int, float)):
            latency = float(r["latency_s"])
    return GroundedOutcome(
        label=label,
        reverted=label == "reverted",
        completed=label == "accepted",
        retries=retries,
        spend_usd=spend,
        latency_s=latency,
        sources=tuple(dict.fromkeys(str(r.get("source")) for r in outcome_records)),
    )


def _loss_table(profile: dict[str, float] | None) -> dict[int, list[float]]:
    return {r["fire"]: r["u"] for r in utility_rows(profile) if "fire" in r}


def realized_loss(action: str, label: Label,
                  profile: dict[str, float] | None = None,
                  *, spend_usd: float | None = None) -> float | None:
    """The realized loss of `action` given the grounded state, in dollars
    (negated step-table utility). None for non-decisive labels. When the
    state is reverted and the action was proceed, a MEASURED spend_usd
    substitutes for the declared fallback call-cost c (measured price beats
    the constant; inert while spend is unlogged)."""
    if label not in _STATE_COL:
        return None
    u = _loss_table(profile)[ACTION_TO_FIRE[action]]
    col = _STATE_COL[label]
    if action == "proceed" and label == "reverted" and spend_usd is not None:
        return float(spend_usd)
    return -u[col]


def loss_bounds(action: str, label: Label,
                profile: dict[str, float] | None = None,
                *, spend_usd: float | None = None) -> tuple[float, float]:
    """(lo, hi) realized loss: decisive labels collapse to a point; the
    non-decisive labels are scored under BOTH possible states — the
    two-sided bound that keeps the ambiguous bucket un-gameable."""
    if label in _STATE_COL:
        x = realized_loss(action, label, profile, spend_usd=spend_usd)
        assert x is not None
        return (x, x)
    lo_hi = sorted((
        realized_loss(action, "accepted", profile),
        realized_loss(action, "reverted", profile, spend_usd=spend_usd),
    ))
    return (float(lo_hi[0]), float(lo_hi[1]))
