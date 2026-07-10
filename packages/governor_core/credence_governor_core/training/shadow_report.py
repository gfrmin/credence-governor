"""shadow_report.py — the membrane shadow's field reading (the Phase-2
exit-criterion instrument, docs/governance-roadmap.md).

Reads `membrane-shadow` records from the observation log and prints, per
utility form: the action distribution and ask-rate — against the two
STATED priors on the record —, the agreement matrix vs the primary
engine's decisions, latency percentiles, and a readout trajectory
summary. Runtime counters (queue drops, errors, respawns) live in the
daemon, not the log: when a daemon answers /report they are printed too.

The stated priors this reading confirms or falsifies:
- hosts-d-task3-report §2a (proplang, frozen): the governor under this
  utility model asks RARELY, through the verdict channel, essentially
  only at decision boundaries.
- docs/membrane-shadow.md (the degenerate-said prediction): the wire's
  implemented `said` subset is action-degenerate, so the latent@1
  shadow fires `block` on every tick — ask-rate exactly 0.

Usage:
    python -m credence_governor_core.training.shadow_report \
        [--log ~/.credence-governor/observations.jsonl] [--daemon URL]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import Counter, defaultdict
from typing import Any

from ..log import ObservationLog

DEFAULT_LOG = os.path.join(
    os.path.expanduser("~"), ".credence-governor", "observations.jsonl")
DEFAULT_DAEMON = "http://127.0.0.1:8787"

STATED_PRIORS = (
    "stated priors on the record:\n"
    "  - hosts-d-task3-report 2a: asks RARELY, verdict channel, essentially\n"
    "    only at decision boundaries\n"
    "  - membrane-shadow register (degenerate said): latent@1 fires block on\n"
    "    every tick, ask-rate exactly 0"
)


def percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def collect(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The per-form reading, pure over the record list (testable)."""
    primary: dict[str, str] = {}
    for r in records:
        if r.get("event_type") == "decision" and isinstance(r.get("in_response_to"), str):
            primary[r["in_response_to"]] = str(r.get("action"))
    forms: dict[str, dict[str, Any]] = {}
    for r in records:
        if r.get("event_type") != "membrane-shadow":
            continue
        form = str(r.get("utility_form"))
        st = forms.setdefault(form, {
            "actions": Counter(),
            "agreement": defaultdict(Counter),   # primary action -> shadow action counts
            "latencies": [],
            "readout_first": None,
            "readout_last": None,
            "sensitivity_true": 0,
            "residual_means": [],
        })
        action = str(r.get("action"))
        st["actions"][action] += 1
        p = primary.get(str(r.get("in_response_to")))
        if p is not None:
            st["agreement"][p][action] += 1
        lat = r.get("latency_ms")
        if isinstance(lat, (int, float)):
            st["latencies"].append(float(lat))
        ro = r.get("readouts") or {}
        if ro:
            st["readout_first"] = st["readout_first"] or ro
            st["readout_last"] = ro
        if ro.get("sensitivity") is True:
            st["sensitivity_true"] += 1
        if isinstance(ro.get("residual_mean"), (int, float)):
            st["residual_means"].append(float(ro["residual_mean"]))
    return forms


def render(forms: dict[str, Any]) -> str:
    lines: list[str] = []
    if not forms:
        return ("no membrane-shadow records yet — is the shadow deployed "
                "(CREDENCE_MEMBRANE_COMMAND) and traffic flowing?")
    for form, st in sorted(forms.items()):
        total = sum(st["actions"].values())
        asks = st["actions"].get("ask", 0)
        lines.append(f"[{form}]  shadow decides: {total}")
        dist = ", ".join(
            f"{a}: {n} ({n / total:.1%})" for a, n in st["actions"].most_common())
        lines.append(f"  actions: {dist}")
        lines.append(f"  ask-rate: {asks / total:.4%} ({asks}/{total})")
        lines.append(f"  {STATED_PRIORS.replace(chr(10), chr(10) + '  ')}")
        agree = st["agreement"]
        if agree:
            joined = sum(sum(c.values()) for c in agree.values())
            same = sum(agree[p].get(p, 0) for p in agree)
            lines.append(
                f"  agreement with primary: {same / joined:.1%} over {joined} joined")
            for p in sorted(agree):
                row = ", ".join(f"{a}: {n}" for a, n in agree[p].most_common())
                lines.append(f"    primary {p:8s} -> shadow {row}")
        lats = sorted(st["latencies"])
        if lats:
            lines.append(
                "  latency ms  p50 {:.2f}  p95 {:.2f}  p99 {:.2f}  (n={})".format(
                    percentile(lats, 0.50), percentile(lats, 0.95),
                    percentile(lats, 0.99), len(lats)))
        rms = st["residual_means"]
        if rms:
            lines.append(
                "  residual_mean  first {:.4f}  last {:.4f}  mean {:.4f};  "
                "sensitivity true on {}/{}".format(
                    rms[0], rms[-1], sum(rms) / len(rms),
                    st["sensitivity_true"], total))
        lines.append("")
    return "\n".join(lines).rstrip()


def daemon_stats(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{url}/report", timeout=2) as r:
            return json.loads(r.read()).get("membrane_shadow")
    except Exception:  # noqa: BLE001 — daemon down is a normal offline reading
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--daemon", default=DEFAULT_DAEMON,
                    help="daemon base URL for live runtime counters ('' to skip)")
    args = ap.parse_args(argv)
    records = ObservationLog(args.log).read()
    print(render(collect(records)))
    if args.daemon:
        stats = daemon_stats(args.daemon)
        if stats is not None:
            print(f"\nlive daemon counters: {json.dumps(stats)}")
        else:
            print("\n(no live daemon reachable for runtime counters — "
                  "drops/errors/respawns need /report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
