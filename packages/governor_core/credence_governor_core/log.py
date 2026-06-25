"""log.py — the append-only observation log (host-side, NON-probabilistic). One
JSON record per line. The daemon appends sensor/decision/route events; on boot it
replays the log to reconstruct the server-side beliefs (via structure_observe /
routing_outcome over the wire), and the report tallies it. Schema (event_type +
fields) preserved so an existing deployment's log still replays.
Port of credence-openclaw daemon/src/log.ts.
"""

from __future__ import annotations

import json
import os
from typing import Any


class ObservationLog:
    def __init__(self, log_path: str):
        self.log_path = log_path

    def append(self, record: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.log_path):
            return []
        out: list[dict[str, Any]] = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def replay_contexts(self) -> list[dict[str, Any]]:
        """(features, observation) pairs for governance replay: each user-responded
        rejoined to its tool-proposed features by in_response_to->event_id; yes->1, no->0.
        Timeouts are not labels (skipped).
        """
        records = self.read()
        features_by_id: dict[str, dict[str, str]] = {}
        for r in records:
            if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str) and r.get("features"):
                features_by_id[r["event_id"]] = r["features"]
        out: list[dict[str, Any]] = []
        for r in records:
            if r.get("event_type") != "user-responded":
                continue
            features = features_by_id.get(str(r.get("in_response_to")))
            if features is None:
                continue
            resp = str(r.get("response") or "")
            if resp == "yes":
                out.append({"features": features, "observation": 1})
            elif resp == "no":
                out.append({"features": features, "observation": 0})
        return out

    def replay_route_outcomes(self) -> list[dict[str, Any]]:
        """(model_id, features, success, human?) for routing replay — route-outcome events."""
        out: list[dict[str, Any]] = []
        for r in self.read():
            if r.get("event_type") != "route-outcome":
                continue
            out.append(
                {
                    "model_id": str(r.get("model_id")),
                    "features": r.get("features") or {},
                    "success": bool(r.get("success")),
                    "human": r.get("human"),
                }
            )
        return out
