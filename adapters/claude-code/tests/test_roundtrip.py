"""Wire-contract parity: the payload the adapter POSTs must deserialise through the
daemon's `event_and_session_from_payload` and feed the server-side extractors to the
right feature buckets. This is the only place the two sides are tied together — at
the JSON contract, not at shared code. Skipped if governor-core isn't importable."""

from __future__ import annotations

import json
import os

import pytest

# Make the sibling core package importable without an install.
_CORE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "governor_core")
)
import sys

if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

core = pytest.importorskip("credence_governor_core")

from credence_governor_claude_code.transcript import session_from_hook  # noqa: E402


def _write(tmp_path, records) -> str:
    p = os.path.join(tmp_path, "t.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return p


def test_payload_deserialises_and_extracts(tmp_path):
    from credence_governor_core import extract_features, extract_safety
    from credence_governor_core.schema import event_and_session_from_payload

    def tool_use(cmd, ts):
        return {"type": "assistant", "timestamp": ts, "isSidechain": False,
                "message": {"role": "assistant",
                            "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                         "input": {"command": cmd}}]}}

    # Three prior identical Bash(ls) calls + the proposed fourth -> a loop.
    records = [
        {"type": "user", "timestamp": "2026-06-25T10:00:00.000Z", "isSidechain": False,
         "message": {"role": "user", "content": "loop ls please"}},
        tool_use("ls", "2026-06-25T10:00:01.000Z"),
        tool_use("ls", "2026-06-25T10:00:02.000Z"),
        tool_use("ls", "2026-06-25T10:00:03.000Z"),
        tool_use("ls", "2026-06-25T10:00:04.000Z"),  # the proposed call (dropped)
    ]
    path = _write(tmp_path, records)
    payload = session_from_hook(
        {"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "transcript_path": path,
         "tool_name": "Bash", "tool_input": {"command": "ls"}}
    )

    event, session = event_and_session_from_payload(payload)
    assert event.tool_name == "Bash"
    # The proposed call was excluded -> exactly the three priors remain.
    assert sum(1 for m in session.messages if m.role == "tool_call") == 3

    feats = {**extract_features(event, session), **extract_safety(event, session)}
    # Three identical priors -> rep-3plus / ident-3plus (the loop signal the daemon decides on).
    assert feats["recent-repetition-count"] == "rep-3plus"
    assert feats["recent-identical-call-count"] == "ident-3plus"
    assert feats["parent-tool-call-name"] == "bash"
