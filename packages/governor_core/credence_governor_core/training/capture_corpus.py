"""capture_corpus.py — fold captured real-dogfood traffic into harm training.

The daemon's opt-in raw capture (capture.RawCaptureLog) writes the raw
(tool_name, input, session) of each governed call to raw_events.jsonl. The agent's
own coding traffic is benign-by-assumption, so these are n0 NEGATIVES — exactly the
real-dogfood volume the harm brain's generic cells (local-write/none,
external-send/internal) need to separate from attacks, which curated negatives cannot
supply. Re-extraction is the point: features are recomputed by the CURRENT extractor,
not read from the capture.

    from credence_governor_core.training.capture_corpus import load_capture
    fold_benign_negatives(counts, load_capture(path), ctx_keys)
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from ..schema import AgentToolEvent, Session, event_and_session_from_payload


def load_capture(path: str) -> Iterator[tuple[AgentToolEvent, Session]]:
    """Yield (event, session) for each captured record, ready for re-extraction.
    Malformed lines are skipped (a truncated/partial tail must not break a build)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield event_and_session_from_payload(rec)
