"""identical_call.py — bucket how many prior tool_calls were the SAME
(tool, arguments) as this one: the argument-level loop signal, distinct from
calling the same tool with different args. Counted session-wide, only for
INFORMATIVE args, with a collision-free content fingerprint.
Output: ident-0 | ident-1 | ident-2 | ident-3plus.
Port of extension/src/features/identical_call.ts.

Note: the TS version used a custom djb2+sdbm fingerprint for compactness. Here we
use a sha1 of the canonical JSON — extraction is now server-side only (the daemon
is the sole hasher), so cross-language hash parity is not required; only
internal stability (identical input -> identical fingerprint) matters, and the
bucket outcomes the parity tests assert depend only on that.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..schema import AgentToolEvent, Session
from .tool_name import bucket


def _fingerprint(value: Any) -> str:
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return "∅"
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _informative(value: Any, tool: str) -> bool:
    # Do the args carry distinguishing information? No, if there are none or the
    # only field's value just echoes the tool name.
    if not isinstance(value, dict):
        return False
    entries = [(k, v) for k, v in value.items() if v is not None and v != ""]
    if not entries:
        return False
    if len(entries) == 1:
        v = entries[0][1]
        if isinstance(v, str) and v.strip().lower() == tool:
            return False
    return True


def extract_recent_identical_call_count(event: AgentToolEvent, session: Session) -> str:
    tool = bucket(event.tool_name)
    if not _informative(event.input, tool):
        return "ident-0"
    fp = _fingerprint(event.input)
    matches = sum(
        1
        for m in session.messages
        if m.role == "tool_call"
        and bucket(m.tool_name or "") == tool
        and _informative(m.input, tool)
        and _fingerprint(m.input) == fp
    )
    if matches == 0:
        return "ident-0"
    if matches == 1:
        return "ident-1"
    if matches == 2:
        return "ident-2"
    return "ident-3plus"
