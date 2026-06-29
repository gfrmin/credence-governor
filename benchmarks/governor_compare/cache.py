# Role: eval
"""cache.py — extract once, score many. The captured records are huge (full session
context, ~2 GB / 2.6k calls), and re-extracting features per governor per run is the
bottleneck. So we run the daemon's exact projection (extract_features ∪ extract_harm)
ONCE per call and cache the tiny result — a dict of ~13 kebab strings plus a slimmed
command string — keyed by call id. Every governor then scores off the cached
FeatureRecord; the deployed daemon decides from `features` directly (no re-extraction,
only the skin round-trip). The cache is regenerable and gitignored.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from credence_governor_core.features import extract_features
from credence_governor_core.safety import extract_harm

import streams as S


@dataclass
class FeatureRecord:
    cid: str
    tool_name: str
    features: dict[str, str]   # the daemon's projection: governance ∪ harm 7-tuple
    cmd_text: str              # slimmed args text (for the regex deny-list rival)
    is_harm: bool
    stream: str
    source: str
    threat_class: str = ""


def command_text(inp: Any) -> str:
    """The args fields a signature guard would grep — capped so the cache stays small."""
    if isinstance(inp, str):
        return inp[:2000]
    if isinstance(inp, dict):
        parts = [str(inp[k]) for k in ("command", "file_path", "path", "new_string", "content", "url")
                 if inp.get(k)]
        return " ".join(parts)[:2000]
    return ""


def extract_record(call: S.LabeledCall) -> FeatureRecord:
    """The daemon's features_for projection (governance ∪ harm), once, off the raw call."""
    feats = {**extract_features(call.event, call.session), **extract_harm(call.event, call.session)}
    return FeatureRecord(call.cid, call.event.tool_name, feats, command_text(call.event.input),
                         call.is_harm, call.stream, call.source, call.threat_class)


def build_cache(out_path: str, capture_path: str = S.DEFAULT_CAPTURE, limit: int | None = None) -> int:
    """Extract the benign capture once → slim JSONL. Returns the record count."""
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for call in S.benign_capture(capture_path, limit=limit):
            f.write(json.dumps(asdict(extract_record(call))) + "\n")
            n += 1
            if n % 200 == 0:
                print(f"  cached {n} benign records…", flush=True)
    return n


def load_cache(path: str) -> Iterator[FeatureRecord]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield FeatureRecord(**json.loads(line))


def attack_records() -> list[FeatureRecord]:
    """The declared red-team, extracted live (only ~20 calls — no cache needed)."""
    return [extract_record(c) for c in S.red_team()]
