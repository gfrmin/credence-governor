"""test_loss.py — the per-record scorer's pinned conventions."""

import pytest

from credence_governor_core.config import UTILITY
from credence_governor_core.membrane import utility_rows

from loss import (
    GroundedOutcome,
    UNGROUNDED,
    loss_bounds,
    merge_outcomes,
    realized_loss,
)


def _outcome(source, **fields):
    base = {"event_type": "outcome", "in_response_to": "e", "source": source,
            "completed": None, "latency_s": None, "spend_usd": None,
            "reverted": None, "retries": None, "error": None}
    base.update(fields)
    return base


def test_column_convention_pinned_against_utility_rows():
    """Col 0 = wasteful (reverted), col 1 = wanted (accepted): block on
    accepted costs λc, proceed on reverted costs c, ask costs q flat —
    indexed from utility_rows itself, never re-derived."""
    c, lam, q = UTILITY["cost"], UTILITY["aversion"], UTILITY["interrupt_cost"]
    assert realized_loss("block", "accepted") == pytest.approx(lam * c)
    assert realized_loss("block", "reverted") == pytest.approx(0.0)
    assert realized_loss("proceed", "reverted") == pytest.approx(c)
    assert realized_loss("proceed", "accepted") == pytest.approx(0.0)
    assert realized_loss("ask", "accepted") == pytest.approx(q)
    assert realized_loss("ask", "reverted") == pytest.approx(q)
    # the algebra that fixes the convention: block beats proceed iff
    # P(wanted) < 1/(1+λ) — only true with these column roles
    rows = {r["fire"]: r["u"] for r in utility_rows() if "fire" in r}
    p = 1 / (1 + lam) - 0.01
    eu_block = p * rows[2][1] + (1 - p) * rows[2][0]
    eu_proceed = p * rows[1][1] + (1 - p) * rows[1][0]
    assert eu_block > eu_proceed


def test_profile_plumbs_through():
    prof = {"cost": 2.0, "aversion": 3.0, "interrupt_cost": 0.5}
    assert realized_loss("block", "accepted", prof) == pytest.approx(6.0)
    assert realized_loss("proceed", "reverted", prof) == pytest.approx(2.0)
    assert realized_loss("ask", "reverted", prof) == pytest.approx(0.5)


def test_spend_substitutes_only_in_proceed_reverted_cell():
    assert realized_loss("proceed", "reverted", spend_usd=1.25) == 1.25
    assert realized_loss("proceed", "accepted", spend_usd=1.25) == 0.0
    assert realized_loss("block", "accepted", spend_usd=1.25) == pytest.approx(
        UTILITY["aversion"] * UTILITY["cost"])


def test_non_decisive_is_none_and_bounds_order():
    for label in ("ambiguous", "hook-only", "ungrounded"):
        assert realized_loss("block", label) is None
        lo, hi = loss_bounds("block", label)
        assert lo <= hi
    # decisive collapses to a point
    assert loss_bounds("proceed", "reverted") == (0.5, 0.5)
    # ambiguous block: 0 if it was wasteful, λc if wanted
    assert loss_bounds("block", "ambiguous") == (0.0, 0.5)


def test_merge_outcomes_precedence_and_telemetry():
    # grounding authoritative for the label even when a hook record disagrees
    merged = merge_outcomes([
        _outcome("result-hook", completed=True, latency_s=1.5),
        _outcome("grounding", reverted=True, retries=2),
    ])
    assert merged.label == "reverted" and merged.retries == 2
    assert merged.latency_s == 1.5              # telemetry union
    assert merged.sources == ("result-hook", "grounding")
    # hook-only: non-decisive regardless of completed=true (shadow mode)
    assert merge_outcomes([_outcome("result-hook", completed=True)]).label == "hook-only"
    # last grounding record wins within the source
    assert merge_outcomes([
        _outcome("grounding", reverted=True),
        _outcome("grounding", completed=True, reverted=False),
    ]).label == "accepted"
    # label recovery table
    assert merge_outcomes([_outcome("grounding", completed=None)]).label == "ambiguous"
    assert merge_outcomes([]) is UNGROUNDED
    assert isinstance(merged, GroundedOutcome)
