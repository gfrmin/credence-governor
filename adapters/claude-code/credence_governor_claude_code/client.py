"""client.py — POST the neutral event to the governor daemon's `/decide`.

Zero-dependency (urllib): the hook is a short-lived subprocess that must start fast
and never block a tool call for long. The caller treats every failure as fail-open.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8787"
DEFAULT_TIMEOUT = 5.0


def base_url() -> str:
    return os.environ.get("CREDENCE_GOVERNOR_URL", DEFAULT_URL)


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
