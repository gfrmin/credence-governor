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

    def replay_harm_contexts(self) -> list[dict[str, Any]]:
        """(features, unsafe) pairs for HARM-belief replay. Only user-responded records that
        carry an explicit `harm_observation` (0|1) are harm evidence — the safety-gate and the
        polarity inversion (harm_obs = 1 − waste_obs) were decided at feedback time and frozen
        on the record, so replay is exact and order-independent and never recomputes them.
        Records without the field (all pre-A2 history) are skipped, so an old log still
        replays its governance labels unchanged and grows no harm evidence retroactively."""
        records = self.read()
        features_by_id: dict[str, dict[str, str]] = {}
        for r in records:
            if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str) and r.get("features"):
                features_by_id[r["event_id"]] = r["features"]
        out: list[dict[str, Any]] = []
        for r in records:
            if r.get("event_type") != "user-responded" or r.get("harm_observation") is None:
                continue
            features = features_by_id.get(str(r.get("in_response_to")))
            if features is None:
                continue
            out.append({"features": features, "unsafe": int(r["harm_observation"])})
        return out

    # outcome records rank by source: grounding sees session continuation (the
    # acceptance signal); openclaw saw the completion in-process; a shadow-mode
    # result-hook's completed=true is universal (everything executed) and so
    # carries the least acceptance information. Unknown sources are not
    # evidence-grade and are skipped.
    _OUTCOME_SOURCE_RANK = {"grounding": 3, "openclaw": 2, "result-hook": 1}

    @staticmethod
    def _outcome_good_bit(record: dict[str, Any]) -> int | None:
        """The latent outcome-evidence bit: 0 iff reverted, 1 iff completed
        and not reverted, None otherwise — ambiguous (incl. completed=False
        without revert evidence) is NOT evidence and is skipped."""
        if record.get("reverted") is True:
            return 0
        if record.get("completed") is True:
            return 1
        return None

    def replay_outcome_contexts(self) -> list[dict[str, Any]]:
        """(event_id, features, good) triples for latent outcome replay: per
        gated event_id ONE representative outcome record — source precedence
        grounding > openclaw > result-hook, last record within the winning
        source — mapped to the good-bit (see _outcome_good_bit). Events whose
        record maps to no bit, or whose tool-proposed features are missing,
        are skipped. Output ordered by each event's FIRST outcome record's
        arrival position (replay order == arrival order, 8.2)."""
        records = self.read()
        features_by_id: dict[str, dict[str, str]] = {}
        for r in records:
            if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str) and r.get("features"):
                features_by_id[r["event_id"]] = r["features"]
        chosen: dict[str, tuple[int, dict[str, Any]]] = {}
        first_pos: dict[str, int] = {}
        for i, r in enumerate(records):
            if r.get("event_type") != "outcome":
                continue
            eid = r.get("in_response_to")
            if not isinstance(eid, str):
                continue
            rank = self._OUTCOME_SOURCE_RANK.get(str(r.get("source")), 0)
            if rank == 0:
                continue
            first_pos.setdefault(eid, i)
            prev = chosen.get(eid)
            if prev is None or rank >= prev[0]:
                chosen[eid] = (rank, r)
        out: list[dict[str, Any]] = []
        for eid in sorted(chosen, key=lambda e: first_pos[e]):
            features = features_by_id.get(eid)
            if features is None:
                continue
            good = self._outcome_good_bit(chosen[eid][1])
            if good is None:
                continue
            out.append({"event_id": eid, "features": features, "good": good})
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
