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


def load_capture(path: str, *, include_truncated: bool = False) -> Iterator[tuple[AgentToolEvent, Session]]:
    """Yield (event, session) for each captured record, ready for re-extraction.

    Two correctness filters, both load-bearing for the training fold:
    - **Truncated records are excluded by default.** A capped string can re-extract to
      DIFFERENT features than the live decision saw (a taint token past the cut), so a
      truncated record is not a faithful negative; pass include_truncated=True only for
      inspection, never for folding.
    - **Deduplicated on event_id** (first occurrence wins). A retried/replayed /decide
      appends the same event_id twice; folding both would double-count that cell.

    Malformed lines are skipped (a partial tail or an interleaved write must not break a build)."""
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("truncated") and not include_truncated:
                continue
            eid = rec.get("event_id")
            if isinstance(eid, str):
                if eid in seen:
                    continue
                seen.add(eid)
            yield event_and_session_from_payload(rec)
