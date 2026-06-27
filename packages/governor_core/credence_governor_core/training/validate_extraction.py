"""validate_extraction.py — does the live extractor reproduce the canonical
training features?

The harm brain (`data/brain/harm_brain.counts.json`) was built by a SEPARATE
extractor copy in `credence_pi_eval` whose per-call features are frozen in
`data_corpora/atbench_claw/events.jsonl`. This script replays the corpus through
the governor's OWN `extract_safety` (via the neutral-schema adapter) and aligns
it to those canonical features by (session_id, idx), reporting per-feature
agreement. Disagreement = the train/runtime fork; the provenance-sensitive
features (taint-flow, injected-imperative) are where it is expected to surface.

Run: python -m credence_governor_core.training.validate_extraction <corpus.json> <events.jsonl>
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from ..safety import extract_safety
from .corpus import iter_atbench

HARM_FEATURES = ["action-class", "taint-flow", "injected-imperative", "cred-exfil-chain"]


def load_canonical(events_path: str) -> dict[tuple[str, int], dict[str, str]]:
    """(session_id, idx) -> the frozen per-call feature dict from events.jsonl."""
    out: dict[tuple[str, int], dict[str, str]] = {}
    with open(events_path) as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            out[(rec["session_id"], rec["idx"])] = rec.get("features", {})
    return out


def run(corpus_path: str, events_path: str) -> dict[str, float]:
    canonical = load_canonical(events_path)
    agree = {f: 0 for f in HARM_FEATURES}
    total = {f: 0 for f in HARM_FEATURES}
    confusion: dict[str, Counter] = {f: Counter() for f in HARM_FEATURES}
    matched = 0

    for call in iter_atbench(corpus_path):
        key = (call.session_id, call.idx)
        canon = canonical.get(key)
        if canon is None:
            continue
        matched += 1
        live = extract_safety(call.event, call.session)
        for f in HARM_FEATURES:
            cv, lv = canon.get(f), live.get(f)
            total[f] += 1
            if cv == lv:
                agree[f] += 1
            else:
                confusion[f][f"canon={cv} live={lv}"] += 1

    print(f"matched calls: {matched} / {len(canonical)} canonical")
    print(f"{'feature':<22}{'agreement':>12}")
    for f in HARM_FEATURES:
        pct = agree[f] / total[f] if total[f] else float("nan")
        print(f"{f:<22}{pct:>11.1%}  ({agree[f]}/{total[f]})")
        for label, n in confusion[f].most_common(4):
            print(f"      {n:>5}  {label}")
    return {f: (agree[f] / total[f] if total[f] else float("nan")) for f in HARM_FEATURES}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    run(sys.argv[1], sys.argv[2])
