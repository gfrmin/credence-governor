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
published package must not assume). Enable with CREDENCE_GOVERNOR_CAPTURE=1 (or a path).

Truncation vs re-extraction: string fields over CREDENCE_GOVERNOR_CAPTURE_MAXLEN
(default 1 MB) are cut so a pathological multi-MB blob cannot run a record away — but
truncation is destructive: a taint token past the cut would re-extract to DIFFERENT
features than the live decision saw, silently mis-celling the record, and truncated
records are excluded from the training fold. The cap is a runaway-size guard, not a
privacy control (opt-in already accepts raw capture), so the default is generous: real
coding traffic (file contents, transcript context) routinely exceeds tens of KB and
must NOT be truncated, or the corpus the capture exists to build is starved. Every
record records whether it was truncated; load_capture excludes truncated records by
default — only faithfully re-extractable records become negatives.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

DEFAULT_MAXLEN = 1_000_000  # 1 MB/string: a runaway guard, not a privacy cap — real
#                             coding traffic must pass untruncated or the corpus starves
_MAX_DEPTH = 40  # bound recursion: a deeply-nested payload must not RecursionError into the decision path
_TRUNC_MARK = "…[truncated]"


def _cap(value: Any, maxlen: int, flag: list[bool], depth: int = 0) -> Any:
    """Recursively truncate over-long strings (and over-deep nesting), preserving
    structure so the payload still round-trips. Sets flag[0] = True if anything was
    cut — a truncated record is not a faithful re-extraction and is excluded from the
    training fold."""
    if depth >= _MAX_DEPTH:
        flag[0] = True
        return _TRUNC_MARK
    if isinstance(value, str):
        if len(value) > maxlen:
            flag[0] = True
            return value[:maxlen] + _TRUNC_MARK
        return value
    if isinstance(value, list):
        return [_cap(v, maxlen, flag, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _cap(v, maxlen, flag, depth + 1) for k, v in value.items()}
    return value


class RawCaptureLog:
    """Append-only raw-payload capture. Construct via from_env() (returns None when the
    feature is off) so the daemon holds None and skips capture entirely when disabled."""

    def __init__(self, path: str, maxlen: int = DEFAULT_MAXLEN):
        self.path = path
        self.maxlen = maxlen
        self._lock = threading.Lock()  # ThreadingHTTPServer ⇒ concurrent decide_sync writers

    @classmethod
    def from_env(cls, default_dir: str) -> RawCaptureLog | None:
        flag = os.environ.get("CREDENCE_GOVERNOR_CAPTURE", "").strip()
        if not flag or flag.lower() in ("0", "false", "no", "off"):
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
        key is dropped — re-extraction is the whole point — and over-long strings capped.
        The write is locked + serialised before touching the file so a capture failure
        (or a concurrent writer) cannot corrupt a line."""
        flag = [False]
        record = {
            "event_id": event_id,
            "tool_name": payload.get("tool_name") or payload.get("toolName") or "",
            "input": _cap(payload.get("input"), self.maxlen, flag),
            "session": _cap(payload.get("session") or {}, self.maxlen, flag),
            "truncated": flag[0],
        }
        line = json.dumps(record) + "\n"  # serialise BEFORE locking the file
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
