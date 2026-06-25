"""Transcript replay: Claude Code JSONL -> neutral wire messages.

The fixtures are minimal hand-written transcript records matching the real schema
(type=user/assistant, message.content blocks, top-level timestamp/isSidechain).
"""

from __future__ import annotations

import json
import os

from credence_governor_claude_code.transcript import (
    drop_proposed,
    messages_from_transcript,
    result_to_text,
    session_from_hook,
)


def _write(tmp_path, records) -> str:
    p = os.path.join(tmp_path, "transcript.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return p


def _user(text, ts="2026-06-25T10:00:00.000Z", sidechain=False):
    return {"type": "user", "timestamp": ts, "isSidechain": sidechain,
            "message": {"role": "user", "content": text}}


def _tool_use(name, inp, ts="2026-06-25T10:00:01.000Z", sidechain=False):
    return {"type": "assistant", "timestamp": ts, "isSidechain": sidechain,
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": name, "input": inp}]}}


def _tool_result(content, ts="2026-06-25T10:00:02.000Z", sidechain=False):
    return {"type": "user", "timestamp": ts, "isSidechain": sidechain,
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": content}]}}


def test_roles_and_order(tmp_path):
    path = _write(tmp_path, [
        _user("hello"),
        _tool_use("Bash", {"command": "ls"}),
        _tool_result("a.txt\nb.txt"),
    ])
    msgs = messages_from_transcript(path)
    assert [m["role"] for m in msgs] == ["user", "tool_call", "tool_result"]
    assert msgs[1]["tool_name"] == "Bash"
    assert msgs[1]["input"] == {"command": "ls"}
    assert msgs[2]["result"] == "a.txt\nb.txt"


def test_sidechain_excluded_by_default(tmp_path):
    path = _write(tmp_path, [
        _user("hi"),
        _tool_use("Read", {"file_path": "x"}, sidechain=True),
    ])
    assert [m["role"] for m in messages_from_transcript(path)] == ["user"]
    assert len(messages_from_transcript(path, include_sidechain=True)) == 2


def test_tool_result_list_content_flattened():
    text = result_to_text([{"type": "text", "text": "alpha"}, {"type": "text", "text": "beta"}])
    assert text == "alpha\nbeta"


def test_drop_proposed_removes_matching_trailing_call():
    msgs = [
        {"role": "tool_call", "tool_name": "Bash", "input": {"command": "ls"}},
        {"role": "tool_call", "tool_name": "Bash", "input": {"command": "pwd"}},
    ]
    drop_proposed(msgs, "Bash", {"command": "pwd"})
    assert [m["input"] for m in msgs] == [{"command": "ls"}]


def test_drop_proposed_keeps_nonmatching_trailing_call():
    msgs = [{"role": "tool_call", "tool_name": "Bash", "input": {"command": "ls"}}]
    drop_proposed(msgs, "Bash", {"command": "different"})
    assert len(msgs) == 1


def test_session_from_hook_excludes_proposed_call(tmp_path):
    # The proposed Bash(pwd) is already persisted to the transcript when PreToolUse
    # fires; the wire `messages` must NOT contain it (repetition counts priors only).
    path = _write(tmp_path, [
        _user("go"),
        _tool_use("Bash", {"command": "ls"}),
        _tool_result("ok"),
        _tool_use("Bash", {"command": "pwd"}),
    ])
    payload = session_from_hook(
        {"hook_event_name": "PreToolUse", "cwd": str(tmp_path),
         "transcript_path": path, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
    )
    assert payload["tool_name"] == "Bash"
    assert payload["input"] == {"command": "pwd"}
    calls = [m for m in payload["session"]["messages"] if m["role"] == "tool_call"]
    assert [c["input"] for c in calls] == [{"command": "ls"}]


def test_project_root_detected(tmp_path):
    os.makedirs(os.path.join(tmp_path, ".git"))
    sub = os.path.join(tmp_path, "src")
    os.makedirs(sub)
    payload = session_from_hook(
        {"hook_event_name": "PreToolUse", "cwd": sub, "transcript_path": "",
         "tool_name": "Read", "tool_input": {}}
    )
    assert payload["session"]["project_root"] == str(tmp_path)
