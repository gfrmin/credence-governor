"""The PostToolUse result path: PreToolUse stashes the decide-time event_id keyed by the
call's identity; PostToolUse recovers it, measures latency, reads completion from the
tool_response, and posts a MEASURED outcome to /result. Every step is best-effort — a stash
miss posts without an event_id, a down daemon is swallowed, and the tool always proceeds.

The daemon and the transcript reads are stubbed; the stash is redirected to a tmp dir via
CREDENCE_GOVERNOR_STATE_DIR so nothing touches the real home.
"""

from __future__ import annotations

import credence_governor_claude_code.hook as hook
import credence_governor_claude_code.pending as pending


def _isolate_stash(monkeypatch, tmp_path):
    monkeypatch.setenv("CREDENCE_GOVERNOR_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("CREDENCE_GOVERNOR_SHADOW", raising=False)
    monkeypatch.delenv("CREDENCE_GOVERNOR_DENY_CATEGORIES", raising=False)


def _capture_results(monkeypatch):
    posted: list[dict] = []
    monkeypatch.setattr(hook.client, "post_result", lambda p: posted.append(p) or {"ok": True})
    return posted


# ── completed_from_tool_response ──────────────────────────────────────────────
def test_completed_reads_error_indicators():
    assert hook.completed_from_tool_response({"stdout": "ok"}) is True
    assert hook.completed_from_tool_response({"is_error": True}) is False
    assert hook.completed_from_tool_response({"isError": True}) is False
    assert hook.completed_from_tool_response({"error": "boom"}) is False
    assert hook.completed_from_tool_response({"success": False}) is False
    assert hook.completed_from_tool_response({"interrupted": True}) is False
    assert hook.completed_from_tool_response("plain string result") is True
    assert hook.completed_from_tool_response(None) is None


# ── PreToolUse stashes; PostToolUse correlates ────────────────────────────────
def test_pre_then_post_correlates_event_id_and_latency(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)
    posted = _capture_results(monkeypatch)
    monkeypatch.setattr(hook.transcript, "session_from_hook", lambda _hi: {"tool_name": "Bash"})
    monkeypatch.setattr(hook.client, "decide", lambda _p: {"action": "proceed", "event_id": "evt_42", "features": {}})

    pre = {"hook_event_name": "PreToolUse", "session_id": "s1",
           "tool_name": "Bash", "tool_input": {"command": "ls"}}
    hook.handle(pre)  # proceed -> None, but the decision is stashed

    post = {"hook_event_name": "PostToolUse", "session_id": "s1",
            "tool_name": "Bash", "tool_input": {"command": "ls"},
            "tool_response": {"stdout": "a\nb"}}
    assert hook.handle(post) is None
    assert len(posted) == 1
    assert posted[0]["event_id"] == "evt_42"
    assert posted[0]["completed"] is True
    assert isinstance(posted[0]["latency_s"], float) and posted[0]["latency_s"] >= 0


def test_post_stash_miss_posts_without_event_id(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)
    posted = _capture_results(monkeypatch)
    post = {"hook_event_name": "PostToolUse", "session_id": "s1",
            "tool_name": "Bash", "tool_input": {"command": "never-stashed"},
            "tool_response": {"is_error": True}}
    assert hook.handle(post) is None
    assert len(posted) == 1
    assert "event_id" not in posted[0]          # daemon-side fallback resolves it
    assert posted[0]["completed"] is False


def test_post_swallows_daemon_down(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)

    def _boom(_p):
        raise ConnectionRefusedError("daemon down")

    monkeypatch.setattr(hook.client, "post_result", _boom)
    post = {"hook_event_name": "PostToolUse", "session_id": "s1",
            "tool_name": "Bash", "tool_input": {"command": "x"}, "tool_response": {}}
    # never raises, never blocks — the tool proceeds
    assert hook.handle(post) is None


def test_pre_without_event_id_stashes_nothing(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)
    posted = _capture_results(monkeypatch)
    monkeypatch.setattr(hook.transcript, "session_from_hook", lambda _hi: {"tool_name": "Bash"})
    # a fail-open proceed carries no event_id ⇒ nothing to correlate
    monkeypatch.setattr(hook.client, "decide", lambda _p: {"action": "proceed", "features": {}})
    hook.handle({"hook_event_name": "PreToolUse", "session_id": "s1",
                 "tool_name": "Bash", "tool_input": {"command": "ls"}})
    # a later PostToolUse for that call finds no stash ⇒ posts without an event_id
    hook.handle({"hook_event_name": "PostToolUse", "session_id": "s1",
                 "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {}})
    assert "event_id" not in posted[0]


# ── stash FIFO for repeated identical calls ───────────────────────────────────
def test_stash_fifo_for_identical_calls(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)
    # two identical calls stashed in order → drained oldest-first
    pending.write_pending("s1", "Bash", {"command": "ls"}, "evt_first", 100.0)
    pending.write_pending("s1", "Bash", {"command": "ls"}, "evt_second", 101.0)
    eid1, lat1 = pending.pop_pending("s1", "Bash", {"command": "ls"}, 102.0)
    eid2, lat2 = pending.pop_pending("s1", "Bash", {"command": "ls"}, 103.0)
    eid3, lat3 = pending.pop_pending("s1", "Bash", {"command": "ls"}, 104.0)
    assert eid1 == "evt_first" and lat1 == 2.0    # 102 - 100
    assert eid2 == "evt_second" and lat2 == 2.0   # 103 - 101
    assert eid3 is None and lat3 is None           # drained


def test_stash_distinct_calls_do_not_collide(monkeypatch, tmp_path):
    _isolate_stash(monkeypatch, tmp_path)
    pending.write_pending("s1", "Bash", {"command": "ls"}, "evt_ls", 1.0)
    pending.write_pending("s1", "Bash", {"command": "pwd"}, "evt_pwd", 1.0)
    assert pending.pop_pending("s1", "Bash", {"command": "pwd"}, 2.0)[0] == "evt_pwd"
    assert pending.pop_pending("s1", "Bash", {"command": "ls"}, 2.0)[0] == "evt_ls"


def test_stash_prunes_stale_entries(monkeypatch, tmp_path):
    import os
    import time

    _isolate_stash(monkeypatch, tmp_path)
    pending.write_pending("s1", "Bash", {"command": "old"}, "evt_old", time.time())
    key = pending.stash_key("s1", "Bash", {"command": "old"})
    path = os.path.join(pending.stash_dir(), key)
    stale = time.time() - (pending.MAX_AGE_S + 100)
    os.utime(path, (stale, stale))  # age it past MAX_AGE (prune reads mtime)
    # any pop triggers prune() and sweeps the stale entry, even for a different key
    pending.pop_pending("s1", "Bash", {"command": "other"}, time.time())
    assert not os.path.exists(path)
