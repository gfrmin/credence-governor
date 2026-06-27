"""capture.py — opt-in raw-event capture for retrospective feature engineering.

The observation log (log.py) stores only the *extracted features* of each decision,
so when the extractor changes (new harm feature, refined action_class) past traffic
cannot be re-derived — the reason the harm brain's generic cells can only be
separated with curated negatives, never real-dogfood volume.

This captures the RAW (tool_name, input, session) payload `extract_safety` consumes,
keyed by event_id, so a later feature-engineering pass re-extracts over real traffic.
The agent's own coding traffic is benign-by-assumption → these become n0 negatives
(training.capture_corpus folds them via build_harm_brain.fold_benign_negatives).

NON-CAUSAL by construction: capture never reads back into a belief or a decision —
pure telemetry, out of scope for Invariant 1. Append-only, one JSON record per line.

OFF by default (raw sessions carry file contents + commands — a privacy posture the
published package must not assume). Enable with CREDENCE_GOVERNOR_CAPTURE=1 (or a path);
string fields are truncated to CREDENCE_GOVERNOR_CAPTURE_MAXLEN (default 8192) so a
single giant tool-result cannot bloat the corpus.
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MAXLEN = 8192
_TRUNC_MARK = "…[truncated]"


def _cap(value: Any, maxlen: int) -> Any:
    """Recursively truncate over-long strings, preserving structure so the payload
    still round-trips through event_and_session_from_payload."""
    if isinstance(value, str):
        return value if len(value) <= maxlen else value[:maxlen] + _TRUNC_MARK
    if isinstance(value, list):
        return [_cap(v, maxlen) for v in value]
    if isinstance(value, dict):
        return {k: _cap(v, maxlen) for k, v in value.items()}
    return value


class RawCaptureLog:
    """Append-only raw-payload capture. Construct via from_env() (returns None when the
    feature is off) so the daemon holds None and skips capture entirely when disabled."""

    def __init__(self, path: str, maxlen: int = DEFAULT_MAXLEN):
        self.path = path
        self.maxlen = maxlen

    @classmethod
    def from_env(cls, default_dir: str) -> RawCaptureLog | None:
        flag = os.environ.get("CREDENCE_GOVERNOR_CAPTURE", "").strip()
        if not flag or flag in ("0", "false", "no", "off"):
            return None
        # A truthy flag enables capture at the default path; an explicit path overrides it.
        path = flag if ("/" in flag or flag.endswith(".jsonl")) else os.path.join(default_dir, "raw_events.jsonl")
        try:
            maxlen = int(os.environ.get("CREDENCE_GOVERNOR_CAPTURE_MAXLEN", DEFAULT_MAXLEN))
        except ValueError:
            maxlen = DEFAULT_MAXLEN
        return cls(path, maxlen)

    def append(self, event_id: str, payload: dict[str, Any]) -> None:
        """Capture the raw (tool_name, input, session) keyed by event_id. The `features`
        key is dropped — re-extraction is the whole point — and over-long strings capped."""
        record = {
            "event_id": event_id,
            "tool_name": payload.get("tool_name") or payload.get("toolName") or "",
            "input": _cap(payload.get("input"), self.maxlen),
            "session": _cap(payload.get("session") or {}, self.maxlen),
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
