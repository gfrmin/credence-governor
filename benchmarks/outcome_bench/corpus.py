"""corpus.py — the bench's ONLY log-reading I/O: one pass over the
observation log, returning the parsed records plus a snapshot manifest
{path, n_lines, sha256, read_at}. The log grows live (verified mid-session
during design), so every driver pins the exact bytes it read and every
downstream artifact embeds its manifest; bench.py scores intersections and
warns on mismatch rather than silently mixing readings."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

DEFAULT_LOG = os.path.join(
    os.path.expanduser("~"), ".credence-governor", "observations.jsonl")


def read_snapshot(path: str = DEFAULT_LOG) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with open(path, "rb") as f:
        raw = f.read()
    manifest = {
        "path": path,
        "n_lines": raw.count(b"\n"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    records = [
        json.loads(line)
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    return records, manifest
