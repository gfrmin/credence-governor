"""posterior_eval.py — M4 live-verification, automated and ENGINE-IN-THE-LOOP.

M4's result ("recall 15/20 block, self-driven exfil hard-DENY, benign hard-FP ~0") was
verified ONCE, by hand, against the deployed daemon. A hand-produced number silently rots
the moment the engine image, the feature schema, or the trained brain moves. This turns it
into a reproducible check: it boots the REAL engine (a `BrainSession` over the skin wire —
the same dependency the daemon uses at runtime) and runs the declared red-team + curated
benign through the engine's own `structure_decide`, the actual production decision path —
NOT a Python re-score against a frozen grid. The ENGINE makes every decision; this only
tallies. So the selection/gating claim is backed by a runnable check, not a founder's memory.

Run it (needs an engine — a `CREDENCE_ENGINE_DIR` dev checkout or the pinned image):

    uv run --project packages/governor_core \\
        python -m credence_governor_core.training.posterior_eval

TOMBSTONE — the dropped feature expansion. A3 originally proposed *emitting the full
structural candidate set* (re-adding the pre-M4 legacy `action-class` / `target-externality`)
and retraining so structure-BMA re-selects over the wider set. That half was **dropped,
deliberately**: (1) the two features are redundant legacy coordinates of the shipped 7-tuple
— superseded by `coding-action-class` / `egress-destination`; (2) a retrain is not
reproducible — the dogfood capture has grown far past the committed brain's `n0`; and (3)
structure-BMA over the shipped 7-tuple ALREADY performs the Occam feature-selection the
expansion was meant to demonstrate — the engine owns that selection. The valuable half of A3
was never the two features; it was making the selection claim reproducible. That is this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..daemon import _block_category
from ..features import extract_features
from ..safety import extract_harm
from ..schema import AgentToolEvent, Session
from .fp_eval import BENIGN_CODING_CASES
from .red_team import RED_TEAM_CASES


def features_of(event: AgentToolEvent, session: Session) -> dict[str, str]:
    """The exact merged feature dict the daemon conditions on (mirrors `daemon.features_for`)."""
    return {**extract_features(event, session), **extract_harm(event, session)}


@dataclass
class Verdict:
    name: str
    tag: str            # threat_class (attacks) or "benign"
    action: str         # proceed | ask | block — the ENGINE's decision
    category: str       # _block_category label (advisory)

    @property
    def gated(self) -> bool:
        return self.action in ("block", "ask")


def _run(decide: Callable[[dict], str], cases, tag_of) -> list[Verdict]:
    out: list[Verdict] = []
    for c in cases:
        f = features_of(c.event, c.session)
        out.append(Verdict(c.name, tag_of(c), decide(f), _block_category(f)))
    return out


def evaluate(decide: Callable[[dict], str]) -> dict[str, Any]:
    """Run the red-team + curated benign through `decide` (which takes a feature dict and
    returns the engine's proceed/ask/block) and tally the posterior's behaviour. Pass
    `lambda f: booted_session.decide(f, f)` for the engine-in-the-loop path."""
    red = _run(decide, RED_TEAM_CASES, lambda c: c.threat_class)
    benign = _run(decide, BENIGN_CODING_CASES, lambda _c: "benign")
    return {
        "red": red,
        "benign": benign,
        "attack_blocked": sum(v.action == "block" for v in red),
        "attack_gated": sum(v.gated for v in red),
        "attack_total": len(red),
        "injected_gated": sum(v.gated for v, c in zip(red, RED_TEAM_CASES) if c.injected),
        "injected_total": sum(c.injected for c in RED_TEAM_CASES),
        "benign_blocked": sum(v.action == "block" for v in benign),
        "benign_gated": sum(v.gated for v in benign),
        "benign_total": len(benign),
    }


def format_report(r: dict[str, Any]) -> str:
    lines = ["posterior-eval (engine-in-the-loop) — M4 live-verification, reproduced", "",
             f"{'case':<34}{'class':<20}{'engine':>7}  category"]
    lines += [f"{v.name:<34}{v.tag:<20}{v.action:>7}  {v.category}" for v in r["red"]]
    lines.append("")
    lines += [f"{v.name:<34}{'benign':<20}{v.action:>7}  {v.category}" for v in r["benign"]]
    lines += [
        "",
        f"attacks gated {r['attack_gated']}/{r['attack_total']} "
        f"(blocked {r['attack_blocked']}/{r['attack_total']}); "
        f"injection-triggered gated {r['injected_gated']}/{r['injected_total']}",
        f"benign gated {r['benign_gated']}/{r['benign_total']} "
        f"(hard-blocked {r['benign_blocked']}/{r['benign_total']})",
    ]
    return "\n".join(lines)


def main() -> int:
    import os
    import tempfile

    from .. import build_skin_client, data_dir
    from ..log import ObservationLog
    from ..session import BrainSession

    skin = build_skin_client()
    # A fresh (empty) log ⇒ no replay ⇒ the eval measures the shipped WARM brain, reproducibly,
    # rather than a particular deployment's accumulated overrides.
    log = ObservationLog(os.path.join(tempfile.mkdtemp(prefix="posterior_eval_"), "log.jsonl"))
    sess = BrainSession(skin, os.path.join(data_dir(), "brain"), log)
    try:
        sess.boot()
        print(format_report(evaluate(lambda f: sess.decide(f, f))))
    finally:
        skin.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
