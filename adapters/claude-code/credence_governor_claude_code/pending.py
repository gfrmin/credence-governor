"""pending.py — correlate a Claude Code PostToolUse with the PreToolUse decision it follows.

Claude Code fires PreToolUse and PostToolUse as SEPARATE subprocesses, so the decide-time
`event_id` from `/decide` is not in hand at PostToolUse. We bridge them through a tiny
on-disk stash keyed by the call's identity (session + tool + input): PreToolUse writes the
event_id there after `/decide`; PostToolUse reads+unlinks it and measures the latency.

The key is content-addressed (sha256 of session_id, tool_name, canonical tool_input), so a
repeat of the SAME call collides. Collisions are disambiguated by a numeric suffix and
drained FIFO — the oldest pending instance of an identical call is matched first (the
in-order reading, since Claude Code completes calls in the order it proposes them). Writes
use O_EXCL so two racing PreToolUse subprocesses can't clobber one slot.

Pure stdlib, no governor-core import (the hook must start fast and fail open); every
operation is best-effort — the caller swallows failures, and a lost stash entry only costs
one latency/event_id measurement, never a blocked tool call. Old entries are pruned
opportunistically (mtime > MAX_AGE) so a crash between Pre and Post can't leak forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

MAX_AGE_S = 3600.0  # prune stash entries older than an hour (a Pre with no matching Post)
_SUFFIX = re.compile(r"-(\d+)$")


def _state_dir() -> str:
    """The governor state directory (`~/.credence-governor` by default). Overridable via
    CREDENCE_GOVERNOR_STATE_DIR — used by tests to keep the stash out of the real home."""
    return os.environ.get("CREDENCE_GOVERNOR_STATE_DIR") or os.path.expanduser("~/.credence-governor")


def stash_dir() -> str:
    return os.path.join(_state_dir(), "pending-results")


def stash_key(session_id: str, tool_name: str, tool_input: Any) -> str:
    """A stable 16-hex identity for a proposed call: sha256 over session, tool and the
    canonical (sorted-key) JSON of the input. Repeats of the same call share this key."""
    canon = json.dumps(tool_input, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{session_id}\0{tool_name}\0{canon}".encode("utf-8")).hexdigest()
    return digest[:16]


def _variants(directory: str, key: str) -> dict[int, str]:
    """Existing stash files for `key`, as {slot_number: filename}. The bare `key` is slot 0;
    `key-N` is slot N. Slots order the FIFO drain (lowest = oldest)."""
    out: dict[int, str] = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return out
    for name in names:
        if name == key:
            out[0] = name
        elif name.startswith(key + "-"):
            m = _SUFFIX.match(name[len(key):])
            if m:
                out[int(m.group(1))] = name
    return out


def prune(directory: str, now: float, max_age: float = MAX_AGE_S) -> None:
    """Drop stash files older than max_age (by mtime). Best-effort; never raises."""
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        path = os.path.join(directory, name)
        try:
            if now - os.path.getmtime(path) > max_age:
                os.unlink(path)
        except OSError:
            pass


def write_pending(session_id: str, tool_name: str, tool_input: Any, event_id: str, now: float) -> None:
    """Stash `event_id` + timestamp for a proposed call. Repeats of an identical call take the
    NEXT slot (max existing + 1) so insertion order is preserved for the FIFO drain; O_EXCL
    guards against a racing writer. Best-effort — raises nothing the caller must handle here
    (the caller wraps this), but we keep it total for its own sake."""
    directory = stash_dir()
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps({"event_id": event_id, "t": now}).encode("utf-8")
    key = stash_key(session_id, tool_name, tool_input)
    while True:
        variants = _variants(directory, key)
        slot = (max(variants) + 1) if variants else 0
        name = key if slot == 0 else f"{key}-{slot}"
        path = os.path.join(directory, name)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue  # a racing writer took this slot; recompute and try the next
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        return


def pop_pending(session_id: str, tool_name: str, tool_input: Any, now: float) -> tuple[str | None, float | None]:
    """Match a completed call to its stashed decision. Reads+unlinks the OLDEST slot for the
    call's key (FIFO) and returns (event_id, latency_s). A miss (no Pre stash, or the file is
    unreadable) returns (None, None) — the caller then posts /result without an event_id and
    the daemon resolves the fallback. Prunes stale entries opportunistically."""
    directory = stash_dir()
    prune(directory, now)
    key = stash_key(session_id, tool_name, tool_input)
    variants = _variants(directory, key)
    if not variants:
        return (None, None)
    path = os.path.join(directory, variants[min(variants)])
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        _silent_unlink(path)
        return (None, None)
    _silent_unlink(path)
    event_id = data.get("event_id")
    t = data.get("t")
    latency_s = (now - t) if isinstance(t, (int, float)) else None
    return (event_id if isinstance(event_id, str) else None, latency_s)


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
