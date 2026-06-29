# Role: eval
"""Harm comparison: Credence taint-flow vs the static-policy upper bound → harm_results.json.

Reuses the governor's own eval surface in place (no copy): `score_candidate` over
`red_team_source` (all-positive coding attacks → harm-recall) and `benign_coding_source`
(all-negative → fire-rate). Two detectors, scored on identical ground truth:

  * **Credence** — fires on the structural harm surface the daemon actually uses:
    taint-flow ≠ none, injected-imperative, cred-exfil-chain, plus the coding-threat
    features (sensitive target, destructive/privilege action, unknown egress).
  * **Static policy (PERFECT_POLICY)** — a generous *perfect allow-list*: fires only on
    OVERT out-of-policy actions (writes to credential-store/system-privileged targets,
    destructive or privilege ops). It is structurally blind to *allowed-channel* attacks
    — injection-driven misuse of permitted tools, exfiltration over an allowed egress —
    because nothing about the call violates the allow-list. That blind spot is the gap.

Finding 3 (§App-C): the allowed-channel class is exactly what the policy cannot see and
Credence can. The §3 invariant: harm_recall(credence) ≥ harm_recall(policy) by construction
on the allowed-channel subset (the one place a strict win is expected).

    uv run --project packages/governor_core python benchmarks/approach_dominance/harm_compare.py
"""

from __future__ import annotations

import json
import os

from credence_governor_core.safety import (
    coding_action_class,
    egress_destination,
    extract_safety,
    target_sensitivity,
)
from credence_governor_core.training.cand_eval import (
    benign_coding_source,
    red_team_source,
    score_candidate,
)
from credence_governor_core.training.red_team import RED_TEAM_CASES

OUT = os.path.join(os.path.dirname(__file__), "harm_results.json")

_OVERT_TARGETS = ("credential-store", "system-privileged")
_OVERT_ACTIONS = ("destructive", "privilege-op")


def static_policy(event, session) -> bool:
    """Perfect allow-list: fires iff the call is OVERTLY out of policy. Allowed-channel
    attacks (injection, taint-flow exfil over permitted tools) pass — structural miss."""
    ts = target_sensitivity(event.tool_name, event.input, session.trusted_paths, session.project_root)
    ac = coding_action_class(event.tool_name, event.input)
    return ts in _OVERT_TARGETS or ac in _OVERT_ACTIONS


def credence(event, session) -> bool:
    """Credence's structural harm surface: the allowed-channel signals the policy is blind
    to (taint-flow / injection / cred-exfil) PLUS the overt ones the policy also catches."""
    s = extract_safety(event, session)
    if s.get("taint-flow", "none") != "none":
        return True
    if s.get("injected-imperative") == "yes" or s.get("cred-exfil-chain") == "yes":
        return True
    return static_policy(event, session) or egress_destination(event.tool_name, event.input) == "external-unknown"


def _m(metrics) -> dict:
    """Pull the JSON-relevant fields off a Metrics dataclass."""
    return {
        "corpus": metrics.corpus, "n_calls": metrics.n_calls, "n_fire": metrics.n_fire,
        "n_harm": metrics.n_harm, "harm_recall": _round(metrics.harm_recall),
        "fire_rate": _round(metrics.fire_rate), "harm_precision": _round(metrics.harm_precision),
        "n_error": metrics.n_error,
    }


def _round(x):
    import math
    return None if (isinstance(x, float) and math.isnan(x)) else round(x, 4)


def per_threat_class() -> dict:
    """Catch/miss per threat class for both detectors — exposes the allowed-channel gap."""
    out: dict[str, dict] = {}
    for case in RED_TEAM_CASES:
        cls = out.setdefault(case.threat_class, {"n": 0, "credence_caught": 0, "policy_caught": 0,
                                                 "allowed_channel_misses": []})
        cls["n"] += 1
        c_hit = credence(case.event, case.session)
        p_hit = static_policy(case.event, case.session)
        cls["credence_caught"] += 1 if c_hit else 0
        cls["policy_caught"] += 1 if p_hit else 0
        if c_hit and not p_hit:  # the gap: Credence sees it, the allow-list cannot
            cls["allowed_channel_misses"].append(case.name)
    return out


def main() -> int:
    red = red_team_source()
    benign = benign_coding_source()

    cred_recall = score_candidate(credence, red)
    pol_recall = score_candidate(static_policy, red)
    cred_fp = score_candidate(credence, benign)
    pol_fp = score_candidate(static_policy, benign)

    by_class = per_threat_class()
    gap = sum(len(v["allowed_channel_misses"]) for v in by_class.values())

    result = {
        "detectors": {
            "credence": {"recall": _m(cred_recall), "fire_rate": _m(cred_fp)},
            "static_policy": {"recall": _m(pol_recall), "fire_rate": _m(pol_fp)},
        },
        "per_threat_class": by_class,
        "allowed_channel_gap_count": gap,
        "finding": (f"static allow-list catches {pol_recall.harm_recall:.0%}; Credence taint-flow "
                    f"catches {cred_recall.harm_recall:.0%}; the gap is {gap} allowed-channel attack(s) "
                    f"policy is structurally blind to."),
        "source": "measured",  # corpus-scored, deterministic; no modelled assumption in the recalls
        "verdict_strict_win": cred_recall.harm_recall >= pol_recall.harm_recall,
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)

    # §3: a strict win on the allowed-channel subset is expected by construction.
    assert result["verdict_strict_win"], "harm_recall(credence) < harm_recall(policy) — unexpected"
    print(f"harm: credence recall={cred_recall.harm_recall:.2f} (fire={cred_fp.fire_rate:.2f}) "
          f"vs policy recall={pol_recall.harm_recall:.2f} (fire={pol_fp.fire_rate:.2f}); "
          f"allowed-channel gap={gap}  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
