# Role: eval
"""Competitor-class config — every assumption most-favourable-to-competitor, in one
place (§App-A). Mirrors the doc's block exactly; the arms in `arms.py` read these.

Upper-bound discipline (§3): each synthetic competitor sits at the *most favourable to
the competitor* end of its declared range. `--competitor-best-case` pushes them further
still (see `best_case()`), and that run's loss map is pasted into the README.
"""

from __future__ import annotations

# Compression class — the BEST a compressor could plausibly be (an upper bound):
#   cost_mult 0.70  = a 30% cut; quality_delta 0.0 = zero quality loss (the steelman).
SYNTH_COMPRESSOR = dict(cost_mult=0.70, quality_delta=0.0, harm_coverage="policy_only")

# TokenShift — a NAMED, REAL point inside the compression class (its published claims).
#   compression 0.20 of input, input is 0.70 of spend ⇒ effective cost_mult = 1 − 0.20·0.70.
TOKENSHIFT = dict(compression=0.20, input_frac=0.70, quality_delta=0.0,
                  latency_delta=0.0, routing=False)

# Static-guard class — perfect allow-list (upper bound on static governance). Caught iff
# an allow-list violation; allowed-channel attacks ⇒ structural miss (priced in harm_compare).
PERFECT_POLICY = dict(allowlist="generous")


def tokenshift_cost_mult() -> float:
    """Effective per-call cost multiplier implied by TokenShift's published params."""
    return 1.0 - TOKENSHIFT["compression"] * TOKENSHIFT["input_frac"]  # 0.86


def best_case(synth: dict) -> dict:
    """`--competitor-best-case`: push the compressor past its favourable bound (a deeper
    cut, still zero quality loss) — the steelman re-run that must still not beat stacked."""
    return {**synth, "cost_mult": round(synth["cost_mult"] * 0.80, 4)}  # 0.70 -> 0.56
