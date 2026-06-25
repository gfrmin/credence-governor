"""client.py — POST the neutral event to the governor daemon's `/decide`.

Zero-dependency (urllib): the hook is a short-lived subprocess that must start fast
and never block a tool call for long. The caller treats every failure as fail-open.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8787"
DEFAULT_TIMEOUT = 5.0

# Shared daemon-process constants — one source for "how to start the daemon", reused by
# the PreToolUse hook's debug hint AND the SessionStart hook (warning text + autostart).
DAEMON_CMD = "credence-governor-daemon"
INSTALL_CMD = "pip install credence-governor-core"
AUTOSTART_ENV = "CREDENCE_GOVERNOR_AUTOSTART"


def base_url() -> str:
    """The daemon base URL. CREDENCE_GOVERNOR_URL is the explicit override; otherwise it
    is composed from CREDENCE_GOVERNOR_HOST / CREDENCE_GOVERNOR_PORT — the SAME vars the
    daemon binds — so ONE relocation override moves the daemon AND both adapter paths
    (/decide + the SessionStart /ready probe) together, with no disjoint-config trap."""
    url = os.environ.get("CREDENCE_GOVERNOR_URL")
    if url:
        return url
    host = os.environ.get("CREDENCE_GOVERNOR_HOST", DEFAULT_HOST)
    port = os.environ.get("CREDENCE_GOVERNOR_PORT", DEFAULT_PORT)
    return f"http://{host}:{port}"


def timeout_s() -> float:
    try:
        return float(os.environ.get("CREDENCE_GOVERNOR_TIMEOUT", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /decide and return the daemon's JSON ({action, features, event_id}).
    Raises on transport/HTTP error — the caller fails open."""
    url = base_url().rstrip("/") + "/decide"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout_s()) as resp:  # noqa: S310 (localhost daemon)
        return json.loads(resp.read().decode("utf-8"))
