# Role: eval
"""Profiles + personas + the realistic region — the governor's Python mirror of
`adapters/openclaw/src/profile.ts` (§5.4 resolved: mirror with a drift-guard test).

A Profile is the 5-tuple the product ships: the value of a correct answer (`reward`),
false-block aversion (`lam` = λ), interruption cost (`q`), harm cost (`harm`), and the
dollar value of a second of wall-clock (`w_time`). The TypeScript adapter is the source
of truth; `tests/test_profile_drift.py` re-reads `profile.ts` and fails if these drift.
(The partial mirror in `governor_core/config.py:UTILITY` renames fields and omits
`w_time`, so it cannot stand in for the personas — hence this dedicated mirror.)

Routing only consults `reward` (Savage: one shared belief, per-profile utility); the
other dials price the EU sensitivity surface and the harm comparison (§App-B personas).
"""

from __future__ import annotations

from dataclasses import dataclass

# Located relative to this file so the drift-guard can find the TS source from anywhere.
import os

PROFILE_TS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "adapters", "openclaw", "src", "profile.ts")
)


@dataclass(frozen=True)
class Profile:
    reward: float   # $ value of a correct answer (the routing coordinate)
    lam: float      # λ — false-block aversion (unitless)
    q: float        # interruption cost ($)
    harm: float     # harm cost ($)
    w_time: float   # time coordinate ($/sec of wall-clock)


# ── PRESETS — byte-for-byte the values in profile.ts (drift-guarded) ──────────
PRESETS: dict[str, Profile] = {
    "cost-saver":    Profile(reward=0.02, lam=0.25, q=0.05, harm=1.0, w_time=0.002),
    "balanced":      Profile(reward=1.0,  lam=1.0,  q=0.02, harm=1.0, w_time=0.014),
    "quality-first": Profile(reward=5.0,  lam=2.0,  q=0.1,  harm=2.0, w_time=0.014),
    "speed-first":   Profile(reward=1.0,  lam=1.0,  q=0.5,  harm=1.0, w_time=0.05),
}

# ── PERSONAS — the §App-B table. q is unspecified in App-B; carry the balanced
#    default (it touches neither routing nor the harm-recall axes the eval scores). ──
PERSONAS: dict[str, Profile] = {
    "indie-hacker":         Profile(reward=0.02, lam=0.25, q=0.02, harm=0.25, w_time=0.002),
    "startup-balanced":     Profile(reward=1.0,  lam=1.0,  q=0.02, harm=1.0,  w_time=0.014),
    "regulated-enterprise": Profile(reward=2.0,  lam=2.0,  q=0.02, harm=2.5,  w_time=0.014),
    "fintech-safety":       Profile(reward=5.0,  lam=2.0,  q=0.02, harm=3.0,  w_time=0.014),
    "quality-research":     Profile(reward=5.0,  lam=2.0,  q=0.02, harm=2.0,  w_time=0.014),
}

# ── Realistic region (§App-B) — the prior the dominance fraction integrates over.
#    Declared, swappable, printed. Excludes the harm-indifferent corner (harm < 0.25). ──
REALISTIC_REGION = {
    "harm": (0.5, 3.0),   # harm ∈ [0.5, 3.0]
    "lam": (0.25, 4.0),   # λ    ∈ [0.25, 4.0]
    "weighting": "uniform",          # §App-B ruling: uniform over the region…
    "sensitivity": "persona",        # …with the persona-weighted integral printed alongside
    "excludes": "harm < 0.25",
}


def routing_rewards() -> dict[str, float]:
    """The per-profile `reward` dials the routing sweep uses (presets ∪ personas).

    Deduplicated by reward value would collapse distinct profiles, so we keep names;
    routing decisions depend only on `reward`, so same-reward profiles route alike (and
    that *is* the finding — one belief, the reward dial alone moves the decision)."""
    return {name: p.reward for name, p in {**PRESETS, **PERSONAS}.items()}
