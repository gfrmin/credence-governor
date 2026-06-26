"""feedback.py — `credence-governor-feedback`: record a human verdict on a governor
decision so the belief learns.

Claude Code's PreToolUse hook has no resolution callback (unlike OpenClaw's onResolution),
so the VOI-gated ask loop can't close itself — you close it explicitly here. `approve`
conditions the governance belief toward allowing that context (the governor was too
cautious); `reject` toward refusing it (the governor was right). Only you give verdicts;
the daemon records them human=true and replays them on boot.

  credence-governor-feedback approve            # the LAST gated call was actually fine
  credence-governor-feedback reject             # the last call was rightly stopped
  credence-governor-feedback approve --event evt_123
  python -m credence_governor_claude_code.feedback approve   # if the script isn't on PATH
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from . import client

# approve => observation 1 (allow this context), reject => 0 (refuse it). yes/no are aliases.
_VERDICT = {"approve": 1, "yes": 1, "reject": 0, "no": 0}


def post_feedback(observation: int, event_id: str | None = None) -> dict:
    """POST /feedback {observation, event_id?} and return the daemon's JSON. Raises on
    transport error so main() can report it."""
    url = client.base_url().rstrip("/") + "/feedback"
    payload: dict = {"observation": observation}
    if event_id:
        payload["event_id"] = event_id
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=client.timeout_s()) as resp:  # noqa: S310 (localhost daemon)
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="credence-governor-feedback",
        description="Tell the governor whether a tool call it gated was actually fine "
        "(approve) or rightly stopped (reject). Conditions the belief and closes the "
        "Claude Code ask loop.",
    )
    ap.add_argument("verdict", choices=sorted(_VERDICT), help="approve|reject (yes|no aliases)")
    ap.add_argument("--event", default=None, help="event_id to correct (default: the last decision)")
    args = ap.parse_args(argv)
    try:
        result = post_feedback(_VERDICT[args.verdict], args.event)
    except (urllib.error.URLError, OSError) as err:
        print(f"credence-governor-feedback: could not reach the daemon ({err}). Is it up?", file=sys.stderr)
        return 1
    if not result.get("ok"):
        print(f"credence-governor-feedback: {result.get('error', 'failed')}", file=sys.stderr)
        return 1
    verb = "approve" if result.get("observation") else "reject"
    print(f"credence-governor-feedback: recorded {verb} on {result.get('event_id')} — belief updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
