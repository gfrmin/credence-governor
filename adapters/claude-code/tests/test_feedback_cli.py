"""credence-governor-feedback CLI: map the verdict to an observation and POST it; map
yes/no aliases; never crash if the daemon is unreachable or returns an error (return 1).
The transport is stubbed so this exercises only the arg/verdict mapping."""

from __future__ import annotations

import urllib.error

import credence_governor_claude_code.feedback as fb


def test_approve_posts_observation_1(monkeypatch):
    calls = []
    monkeypatch.setattr(fb, "post_feedback",
                        lambda obs, event=None: (calls.append((obs, event)), {"ok": True, "observation": obs, "event_id": "evt_x"})[1])
    assert fb.main(["approve"]) == 0
    assert calls == [(1, None)]


def test_reject_with_event_posts_observation_0(monkeypatch):
    calls = []
    monkeypatch.setattr(fb, "post_feedback",
                        lambda obs, event=None: (calls.append((obs, event)), {"ok": True, "observation": obs, "event_id": event})[1])
    assert fb.main(["reject", "--event", "evt_7"]) == 0
    assert calls == [(0, "evt_7")]


def test_yes_no_aliases(monkeypatch):
    seen = []
    monkeypatch.setattr(fb, "post_feedback",
                        lambda obs, event=None: (seen.append(obs), {"ok": True, "observation": obs})[1])
    fb.main(["yes"])
    fb.main(["no"])
    assert seen == [1, 0]


def test_daemon_unreachable_returns_1(monkeypatch):
    def boom(obs, event=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(fb, "post_feedback", boom)
    assert fb.main(["approve"]) == 1


def test_server_error_returns_1(monkeypatch):
    monkeypatch.setattr(fb, "post_feedback", lambda obs, event=None: {"ok": False, "error": "unknown event"})
    assert fb.main(["approve", "--event", "nope"]) == 1
