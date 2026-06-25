"""SessionStart hook: daemon-down warning + opt-in autostart. _ready / _spawn_daemon /
_await_ready are monkeypatched so no real network or process is touched — every branch
of handle() is asserted by its emitted systemMessage + additionalContext (or None).
"""

from __future__ import annotations

import json

import pytest

from credence_governor_claude_code import session_start as ss


@pytest.fixture(autouse=True)
def _fixed_url(monkeypatch):
    monkeypatch.setattr(ss.client, "base_url", lambda: "http://127.0.0.1:8787")
    monkeypatch.delenv("CREDENCE_GOVERNOR_AUTOSTART", raising=False)


def _ctx(out):
    return out["hookSpecificOutput"]["additionalContext"]


def test_daemon_up_is_silent(monkeypatch):
    monkeypatch.setattr(ss, "_ready", lambda url, t: True)
    assert ss.handle({"source": "startup"}) is None


def test_down_autostart_off_warns_with_start_command(monkeypatch):
    monkeypatch.setattr(ss, "_ready", lambda url, t: False)
    out = ss.handle({"source": "startup"})
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert ss.DAEMON_CMD in out["systemMessage"]
    assert "status=OFFLINE" in _ctx(out)
    assert "ungoverned" in _ctx(out)


def test_down_autostart_on_command_missing(monkeypatch):
    monkeypatch.setenv("CREDENCE_GOVERNOR_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_ready", lambda url, t: False)
    monkeypatch.setattr(ss, "_spawn_daemon", lambda url: False)
    out = ss.handle({"source": "startup"})
    assert ss.INSTALL_CMD in out["systemMessage"]
    assert "not installed" in _ctx(out)


def test_down_autostart_on_came_up_online(monkeypatch):
    monkeypatch.setenv("CREDENCE_GOVERNOR_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_ready", lambda url, t: False)  # initial + re-probe both down
    monkeypatch.setattr(ss, "_spawn_daemon", lambda url: True)
    monkeypatch.setattr(ss, "_await_ready", lambda url, rt, budget: True)
    out = ss.handle({"source": "startup"})
    assert "status=ONLINE" in _ctx(out)
    assert "now ready" in out["systemMessage"]


def test_down_autostart_on_still_booting_starting(monkeypatch):
    monkeypatch.setenv("CREDENCE_GOVERNOR_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_ready", lambda url, t: False)
    monkeypatch.setattr(ss, "_spawn_daemon", lambda url: True)
    monkeypatch.setattr(ss, "_await_ready", lambda url, rt, budget: False)
    out = ss.handle({"source": "startup"})
    assert "status=STARTING" in _ctx(out)


def test_autostart_reprobe_wins_race_silent(monkeypatch):
    # first probe down, re-probe up (another harness started it) -> silent, no spawn
    seq = iter([False, True])
    monkeypatch.setenv("CREDENCE_GOVERNOR_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_ready", lambda url, t: next(seq))

    def _boom(*_a):
        raise AssertionError("must not spawn when re-probe finds the daemon up")

    monkeypatch.setattr(ss, "_spawn_daemon", _boom)
    assert ss.handle({"source": "resume"}) is None


def test_autostart_skips_remote_url(monkeypatch):
    # a non-loopback configured URL must NOT autostart a local daemon — warn-only
    monkeypatch.setattr(ss.client, "base_url", lambda: "http://10.0.0.5:8787")
    monkeypatch.setenv("CREDENCE_GOVERNOR_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_ready", lambda url, t: False)

    def _boom(*_a):
        raise AssertionError("must not autostart a remote daemon")

    monkeypatch.setattr(ss, "_spawn_daemon", _boom)
    out = ss.handle({"source": "startup"})
    assert "status=OFFLINE" in out["hookSpecificOutput"]["additionalContext"]


def test_main_fail_open_on_malformed_stdin(monkeypatch):
    monkeypatch.setattr(ss.sys.stdin, "read", lambda: "{not json")
    assert ss.main() == 0  # never raises, never blocks the session


def test_output_shape():
    out = ss._offline("http://x:8787", command_missing=False)
    assert json.dumps(out)  # serialisable
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
