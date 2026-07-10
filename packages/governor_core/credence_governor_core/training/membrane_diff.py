"""membrane_diff.py — H's differential gate (HOSTS_PLAN 2.8), engine
against engine over the SAME corpora and the SAME decision surface.

Boots BOTH engines — the pinned Julia credence-skin (`BrainSession`)
and the proplang membrane driver (`MembraneSession`) — and runs the
declared red-team + curated benign through each engine's own decision
path via `posterior_eval.evaluate`. WASTE-ONLY on both sides (no harm
coordinate is passed to either), so the comparison isolates the waste
engine swap and nothing else: prior parity is impossible by doctrine
(Beta(2,2)/p_edge vs 2^-dl), so the gate is DECISION-LEVEL agreement,
with EVERY disagreement enumerated for author review — never averaged
away.

Exit status IS the gate: 0 iff agreement >= threshold (default 0.95,
register item 8.5; the author reviews the enumeration either way).

Run (needs both engines):

    CREDENCE_MEMBRANE_COMMAND=/path/to/proplang-govhost \\
    uv run --project packages/governor_core \\
        python -m credence_governor_core.training.membrane_diff
"""

from __future__ import annotations

import argparse
import os
import tempfile
from typing import Any

from .. import build_skin_client, data_dir
from ..log import ObservationLog
from ..membrane import build_membrane_session
from ..session import BrainSession
from .posterior_eval import evaluate


def compare(rj: dict[str, Any], rm: dict[str, Any]) -> dict[str, Any]:
    """Pair the two runs' verdicts case-by-case (same declared corpora,
    same order) and enumerate every disagreement."""
    pairs = list(zip(rj["red"] + rj["benign"], rm["red"] + rm["benign"]))
    rows = []
    agree = 0
    for vj, vm in pairs:
        assert vj.name == vm.name, "corpus order drifted between runs"
        same = vj.action == vm.action
        agree += int(same)
        rows.append((vj.name, vj.tag, vj.action, vm.action, same))
    return {
        "rows": rows,
        "agree": agree,
        "total": len(pairs),
        "agreement": agree / len(pairs) if pairs else 1.0,
    }


def format_diff(c: dict[str, Any]) -> str:
    lines = [
        "membrane differential (HOSTS_PLAN 2.8) — julia vs proplang, waste-only",
        "",
        f"{'case':<34}{'class':<20}{'julia':>7}{'membrane':>10}  agree",
    ]
    for name, tag, aj, am, same in c["rows"]:
        mark = "" if same else "  << DISAGREE"
        lines.append(f"{name:<34}{tag:<20}{aj:>7}{am:>10}{mark}")
    lines += [
        "",
        f"agreement {c['agree']}/{c['total']} = {c['agreement']:.3f}",
        "disagreements (enumerated for author review):",
    ]
    ds = [r for r in c["rows"] if not r[4]]
    if ds:
        lines += [f"  {name} [{tag}]: julia={aj} membrane={am}"
                  for name, tag, aj, am, _ in ds]
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, default=0.95,
                    help="decision-agreement gate (register 8.5; default 0.95)")
    args = ap.parse_args(argv)

    brain = os.path.join(data_dir(), "brain")

    # fresh logs => both engines measure their shipped WARM state,
    # reproducibly (the posterior_eval discipline)
    tmp = tempfile.mkdtemp(prefix="membrane_diff_")
    jlog = ObservationLog(os.path.join(tmp, "julia.jsonl"))
    mlog = ObservationLog(os.path.join(tmp, "membrane.jsonl"))

    skin = build_skin_client()
    jsess = BrainSession(skin, brain, jlog)
    msess = build_membrane_session(brain, mlog)
    try:
        jsess.boot()
        msess.boot()
        rj = evaluate(lambda f: jsess.decide(f))   # waste-only: no harm passed
        rm = evaluate(lambda f: msess.decide(f))   # waste-only by scope (epoch 1)
        c = compare(rj, rm)
        print(format_diff(c))
        return 0 if c["agreement"] >= args.threshold else 1
    finally:
        skin.shutdown()
        msess.client.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
