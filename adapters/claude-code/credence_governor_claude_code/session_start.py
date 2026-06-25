"""session_start.py — the Claude Code SessionStart hook entry point.

At the start of every session (startup / resume / clear / compact) Claude Code pipes a
small JSON event on stdin; we probe the governor daemon's GET /ready and, if it is DOWN,
surface a clear warning to BOTH the user (systemMessage) and Claude
(hookSpecificOutput.additionalContext) so the ungoverned, fail-open state is never silent.

Opt-in autostart: if CREDENCE_GOVERNOR_AUTOSTART is truthy and the daemon is down, we
spawn `credence-governor-daemon` DETACHED (survives the hook + the session) and idempotent
(only ever when /ready already failed; /ready, not the spawn, is the source of truth — and
the daemon binds its port BEFORE booting the engine, so a losing concurrent spawn exits
fast on EADDRINUSE rather than booting a second engine), then poll /ready for a short
budget and report ONLINE / STARTING. Autostart is default-OFF and loopback-only: booting
the engine starts Julia (~18s) and the daemon is a shared service, so silent heavy
autostart is wrong, and a remote configured URL is never launched locally.

Fail-open is absolute: the governor only ever ADDS friction. Any error here — bad stdin,
no daemon, a failed spawn, a timeout — prints nothing or a plain warning and exits 0. It
never blocks or crashes the session, and it never touches a tool call.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

from . import client  # reuse base_url() + the shared daemon constants (DRY)

# Single source (client.py): the daemon URL, the start/install commands, the autostart env.
DAEMON_CMD = client.DAEMON_CMD
INSTALL_CMD = client.INSTALL_CMD
AUTOSTART_ENV = client.AUTOSTART_ENV

DEFAULT_READY_TIMEOUT = 1.5     # seconds — a SessionStart probe must be quick
DEFAULT_AUTOSTART_WAIT = 8.0    # seconds — post-spawn poll budget (engine boot ~18s)
MAX_AUTOSTART_WAIT = 25.0       # keep total work under the hooks.json timeout (30s)
# Hosts we may locally autostart a daemon for. A non-loopback URL means a REMOTE daemon
# that we must not try to launch on this machine — warn-only there.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", ""}

# A localhost probe must ignore any HTTP(S)_PROXY, else a proxy makes /ready always
# "fail" and we would warn / autostart spuriously.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _debug(msg: str) -> None:
    if os.environ.get("CREDENCE_GOVERNOR_DEBUG"):
        sys.stderr.write(f"credence-governor[session-start]: {msg}\n")


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    return json.loads(raw) if raw and raw.strip() else {}


# ── the /ready probe (urllib, short timeout, fail-open) ──
def _ready(url: str, timeout: float) -> bool:
    """True iff GET {url}/ready answers 2xx within `timeout`. Never raises."""
    req = urllib.request.Request(url.rstrip("/") + "/ready", method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 (localhost daemon)
            return 200 <= int(getattr(resp, "status", 0)) < 300
    except Exception as err:  # connection refused / timeout / HTTP error -> down
        _debug(f"/ready probe failed (treating as down): {err}")
        return False


# ── opt-in detached autostart ──
def _is_loopback(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "").lower() in _LOOPBACK_HOSTS


def _daemon_command() -> list[str]:
    override = os.environ.get("CREDENCE_GOVERNOR_DAEMON_CMD")
    return shlex.split(override) if override else [DAEMON_CMD]


def _spawn_env(url: str) -> dict[str, str]:
    """Inherit the env but pin the daemon's bind to the SAME host/port we probe, so the
    autostarted daemon answers at exactly the configured URL (not a stale default)."""
    env = dict(os.environ)
    parts = urllib.parse.urlsplit(url)
    if parts.hostname:
        env["CREDENCE_GOVERNOR_HOST"] = parts.hostname
    if parts.port:
        env["CREDENCE_GOVERNOR_PORT"] = str(parts.port)
    return env


def _daemon_log_path() -> str:
    return os.environ.get(
        "CREDENCE_GOVERNOR_DAEMON_LOG",
        os.path.join(os.path.expanduser("~"), ".credence-governor", "daemon.log"),
    )


def _open_daemon_log():
    path = _daemon_log_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return open(path, "ab")
    except Exception:
        return subprocess.DEVNULL


def _spawn_daemon(url: str) -> bool:
    """Spawn the daemon DETACHED so it survives this hook and the session. Returns
    True if a spawn was launched, False if the command is not installed. Never raises.

    The daemon binds the host/port from `url` (via _spawn_env), so it answers at exactly
    the URL we probe. Idempotency/races are the CALLER's job via /ready (the source of
    truth): we only reach here once /ready already failed, and if a concurrent daemon
    already holds the port this child fails to bind and exits fast (the daemon binds
    BEFORE booting the engine) — no second persistent daemon, no zombie (detached +
    reparented to init, which reaps it)."""
    cmd = _daemon_command()
    exe = shutil.which(cmd[0])
    if exe is None:
        _debug(f"daemon command not found on PATH: {cmd[0]!r}")
        return False
    log = _open_daemon_log()
    try:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "close_fds": True,  # do NOT inherit Claude Code's stdout pipe into the daemon
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True  # setsid: own session, survives hook exit
        else:  # best-effort detach on Windows
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        subprocess.Popen([exe, *cmd[1:]], env=_spawn_env(url), **kwargs)  # noqa: S603 (trusted local command)
        _debug("spawned detached daemon: " + " ".join([exe, *cmd[1:]]))
        return True
    except FileNotFoundError:
        return False
    except Exception as err:  # any spawn failure -> warn, fail-open
        _debug(f"daemon spawn failed (failing open): {err}")
        return False
    finally:
        if log is not subprocess.DEVNULL:
            try:
                log.close()  # the child kept its own dup of the fd
            except Exception:
                pass


def _await_ready(url: str, ready_timeout: float, budget: float) -> bool:
    deadline = time.monotonic() + budget
    while True:
        if _ready(url, ready_timeout):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(1.0, remaining))


# ── output builders (systemMessage -> user; additionalContext -> Claude) ──
def _output(context: str, system_message: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    if system_message:
        out["systemMessage"] = system_message
    return out


def _offline(url: str, *, command_missing: bool) -> dict[str, Any]:
    if command_missing:
        system = (
            f"credence-governor: CREDENCE_GOVERNOR_AUTOSTART is set but `{DAEMON_CMD}` "
            f"was not found on PATH.\n"
            f"Install the daemon:  {INSTALL_CMD}\n"
            f"Then it auto-starts next session. Tool calls this session are ungoverned "
            f"(fail-open)."
        )
        extra = "the daemon is not installed; "
    else:
        system = (
            f"credence-governor: governance daemon is DOWN at {url} — tool calls this "
            f"session are ungoverned (fail-open by design).\n"
            f"Start it:             {DAEMON_CMD}\n"
            f"Auto-start next time: export {AUTOSTART_ENV}=1\n"
            f"Verify:               curl -s {url}/ready"
        )
        extra = ""
    context = (
        f"[credence-governor] status=OFFLINE. The Bayesian tool-call governor daemon is "
        f"not reachable at {url}, so PreToolUse governance (loop/waste/safety gating) is "
        f"INACTIVE for this session; {extra}every tool call proceeds ungoverned (fail-open "
        f"by design). Do not assume any tool call has been safety-checked by the governor. "
        f"To enable governance the user can run `{DAEMON_CMD}`."
    )
    return _output(context, system)


def _starting(url: str) -> dict[str, Any]:
    system = (
        f"credence-governor: daemon was down — started it in the background (engine boot "
        f"~18s).\n"
        f"Governance engages within the next few tool calls; until then tool calls proceed "
        f"ungoverned (fail-open).\n"
        f"Verify:  curl -s {url}/ready"
    )
    context = (
        f"[credence-governor] status=STARTING. The governor daemon was auto-started and is "
        f"still booting the engine (~18s). Until {url}/ready succeeds, PreToolUse governance "
        f"is inactive and tool calls proceed ungoverned (fail-open). It should be active "
        f"shortly."
    )
    return _output(context, system)


def _online(url: str) -> dict[str, Any]:
    system = (
        f"credence-governor: daemon was down — auto-started it and it is now ready at {url}. "
        f"Bayesian tool-call governance is active for this session."
    )
    context = (
        "[credence-governor] status=ONLINE (auto-started this session). PreToolUse "
        "governance (loop/waste/safety gating) is active; some tool calls may be gated to "
        "ask/block."
    )
    return _output(context, system)


# ── pure core ──
def handle(hook_input: dict[str, Any]) -> dict[str, Any] | None:
    """A SessionStart payload -> the stdout JSON, or None to print nothing.
    Healthy daemon -> None (silent, no spam). Down -> warn (+ optional autostart)."""
    url = client.base_url()
    ready_timeout = _float_env("CREDENCE_GOVERNOR_READY_TIMEOUT", DEFAULT_READY_TIMEOUT)
    source = str(hook_input.get("source") or "")

    if _ready(url, ready_timeout):
        _debug(f"daemon ready (source={source}) — silent")
        return None  # up -> no message; never spam a healthy session

    if not _truthy(AUTOSTART_ENV):
        _debug(f"daemon down, autostart off (source={source}) — warn-only")
        return _offline(url, command_missing=False)

    if not _is_loopback(url):
        # A remote daemon can't be launched from here; warn-only rather than spawn a
        # local daemon that the configured (remote) URL would never reach.
        _debug(f"daemon down but {url} is not loopback — not autostarting a remote daemon")
        return _offline(url, command_missing=False)

    # autostart: re-probe to narrow the race, then spawn detached + idempotent.
    if _ready(url, ready_timeout):
        return None
    if not _spawn_daemon(url):
        return _offline(url, command_missing=True)

    wait = min(
        MAX_AUTOSTART_WAIT,
        max(0.0, _float_env("CREDENCE_GOVERNOR_AUTOSTART_WAIT", DEFAULT_AUTOSTART_WAIT)),
    )
    if _await_ready(url, ready_timeout, wait):
        _debug("autostart: daemon came up within budget")
        return _online(url)
    _debug("autostart: daemon still booting after budget")
    return _starting(url)


def main() -> int:
    try:
        hook_input = _read_stdin()
    except (ValueError, OSError) as err:
        _debug(f"unreadable stdin (failing open): {err}")
        return 0
    try:
        out = handle(hook_input)
    except Exception as err:  # fail-open: never crash a session
        _debug(f"session-start error (failing open): {err}")
        return 0
    if out is not None:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
