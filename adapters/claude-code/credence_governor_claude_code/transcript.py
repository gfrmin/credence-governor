"""transcript.py — Claude Code transcript JSONL -> the neutral wire `session`.

The adapter's whole job is native-events -> the harness-neutral schema the daemon
extracts from (see ../../packages/governor_core/credence_governor_core/schema.py).
A Claude Code PreToolUse hook hands us `transcript_path` (a JSONL of the session so
far) + the proposed `tool_name`/`tool_input`. We replay the transcript into the
`messages` list the server-side extractors expect:

  user        — a real user prompt (drives time-since-user)
  assistant   — model prose (kept only as a turn marker)
  tool_call   — an assistant `tool_use` block (drives repetition / parent-tool / loops)
  tool_result — a user `tool_result` block (the taint SOURCE for safety)

Two correctness points the extractors depend on:
  • the PROPOSED call must NOT appear in `messages` (repetition/identical_call count
    PRIOR calls only). Claude Code persists the assistant `tool_use` to the transcript
    *before* firing PreToolUse, so we drop the trailing tool_call iff it matches.
  • sidechain (subagent) turns are excluded by default — they would pollute the main
    thread's loop counts with a subagent's unrelated calls.

Pure stdlib, no governor-core import: the hook must start fast and fail open. The
shared contract is the JSON key set, not shared code.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable


def _iter_jsonl(path: str) -> Iterable[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(rec, dict):
                yield rec


def _blocks(content: Any) -> list[Any]:
    """Normalise a message `content` to a list of blocks (a bare string is one
    text block)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def result_to_text(content: Any) -> str:
    """Flatten a tool_result's content to plain text so taint tokens read cleanly.
    Claude Code tool_result content is a string or a list of `{type:text,text}` (and
    occasionally nested `{content:[...]}`)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    parts.append(b["text"])
                elif "content" in b:
                    parts.append(result_to_text(b["content"]))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


def _has_text(blocks: list[Any]) -> bool:
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
            return True
        if isinstance(b, str) and b.strip():
            return True
    return False


def messages_from_transcript(path: str, include_sidechain: bool = False) -> list[dict[str, Any]]:
    """Replay a Claude Code transcript into neutral wire messages, in order."""
    out: list[dict[str, Any]] = []
    for rec in _iter_jsonl(path):
        if rec.get("type") not in ("user", "assistant"):
            continue
        if rec.get("isSidechain") and not include_sidechain:
            continue
        ts = rec.get("timestamp")
        message = rec.get("message") or {}
        role = message.get("role")
        blocks = _blocks(message.get("content"))

        if role == "assistant":
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    out.append(
                        {
                            "role": "tool_call",
                            "tool_name": b.get("name"),
                            "input": b.get("input"),
                            "timestamp": ts,
                        }
                    )
                elif b.get("type") == "text" and (b.get("text") or "").strip():
                    out.append({"role": "assistant", "timestamp": ts})
        elif role == "user":
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(
                        {"role": "tool_result", "result": result_to_text(b.get("content")), "timestamp": ts}
                    )
            # A user record carrying tool_result blocks is a tool delivery, not a
            # human turn; only emit a user message when there is genuine user text.
            if _has_text(blocks):
                out.append({"role": "user", "timestamp": ts})
    return out


def drop_proposed(messages: list[dict[str, Any]], tool_name: str, tool_input: Any) -> list[dict[str, Any]]:
    """Remove the trailing tool_call iff it is the proposed call (already persisted
    to the transcript by the time PreToolUse fires). Only the LAST tool_call is a
    candidate; if it doesn't match (transcript not yet flushed) nothing is dropped."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "tool_call":
            if messages[i].get("tool_name") == tool_name and messages[i].get("input") == tool_input:
                del messages[i]
            break
    return messages


def find_project_root(cwd: str) -> str:
    """Nearest enclosing dir containing a `.git` (file or dir), or "" if none —
    feeds the working-directory-relative feature (project-root/subdir/outside)."""
    cur = os.path.abspath(cwd) if cwd else ""
    while cur and cur != os.path.dirname(cur):
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        cur = os.path.dirname(cur)
    return ""


def session_from_hook(hook_input: dict[str, Any]) -> dict[str, Any]:
    """A PreToolUse hook payload -> the `/decide` request body the daemon extracts
    from (neutral AgentToolEvent + Session, snake_case keys)."""
    cwd = hook_input.get("cwd") or ""
    transcript = hook_input.get("transcript_path") or ""
    tool_name = hook_input.get("tool_name") or ""
    tool_input = hook_input.get("tool_input")

    messages: list[dict[str, Any]] = []
    if transcript and os.path.exists(transcript):
        messages = messages_from_transcript(transcript)
        drop_proposed(messages, tool_name, tool_input)

    return {
        "tool_name": tool_name,
        "input": tool_input,
        "session": {
            "cwd": cwd,
            "project_root": find_project_root(cwd),
            "messages": messages,
        },
    }
