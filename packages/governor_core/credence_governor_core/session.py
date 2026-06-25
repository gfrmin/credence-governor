"""session.py — the daemon's brain orchestration over the skin wire. Boots the
three beliefs server-side (governance/waste, harm, routing — warm-seeded from the
data/brain/*.counts.json, shipped inline), replays the local observation log on
top, and exposes the per-event operations the HTTP handler needs. Holds only
opaque server-side handles; ALL inference and decisions are engine-side.
Port of credence-openclaw daemon/src/session.ts.

The structure_*/routing_* verbs are protocol-1.2 additions the engine's Python
credence-skin-client does not yet wrap; we drive them through the client's generic
JSON-RPC `_call`. (DRY follow-up: add public wrappers to the engine client for
parity with the TS client — see the plan's open questions.)
"""

from __future__ import annotations

import json
import os
from typing import Any

from .config import GOVERNANCE, HARM, ROUTING, UTILITY
from .log import ObservationLog


def _read_counts(brain_dir: str, file: str) -> Any | None:
    p = os.path.join(brain_dir, file)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class BrainSession:
    def __init__(self, skin: Any, brain_dir: str, log: ObservationLog):
        self.skin = skin
        self.brain_dir = brain_dir
        self.log = log
        self.waste: dict[str, str] | None = None
        self.harm: dict[str, str] | None = None
        self.routing: str | None = None

    def _verb(self, method: str, params: dict[str, Any]) -> Any:
        return self.skin._call(method, params)

    def boot(self) -> None:
        """Build the server-side beliefs (warm-seeded), then replay the local log on top."""
        self.skin.initialize()

        self.waste = self._verb(
            "structure_bma",
            {
                "feature_names": GOVERNANCE["feature_names"],
                "feature_values": GOVERNANCE["feature_values"],
                "alpha0": UTILITY["alpha0"],
                "beta0": UTILITY["beta0"],
                "p_edge": UTILITY["p_edge"],
                "warm_counts": _read_counts(self.brain_dir, GOVERNANCE["warm_counts_file"]),
            },
        )

        harm_counts = _read_counts(self.brain_dir, HARM["warm_counts_file"])
        if harm_counts:
            self.harm = self._verb(
                "structure_bma",
                {
                    "feature_names": HARM["feature_names"],
                    "feature_values": HARM["feature_values"],
                    "alpha0": UTILITY["alpha0"],
                    "beta0": UTILITY["beta0"],
                    "p_edge": UTILITY["p_edge"],
                    "warm_counts": harm_counts,
                },
            )

        r = self._verb(
            "routing_init",
            {
                "feature_names": ROUTING["feature_names"],
                "feature_values": ROUTING["feature_values"],
                "roster": ROUTING["roster"],
                "reward": UTILITY["reward"],
                "emission_prior": ROUTING["emission_prior"],
                "warm_counts": _read_counts(self.brain_dir, ROUTING["warm_counts_file"]),
            },
        )
        self.routing = r.get("routing_state_id")

        # Replay the local log on top of the warm beliefs (order-independent => exact).
        assert self.waste is not None
        for ctx in self.log.replay_contexts():
            self._verb(
                "structure_observe",
                {
                    "model_id": self.waste["model_id"],
                    "state_id": self.waste["state_id"],
                    "features": ctx["features"],
                    "observation": ctx["observation"],
                },
            )
        if self.routing:
            for o in self.log.replay_route_outcomes():
                self._verb(
                    "routing_outcome",
                    {
                        "routing_state_id": self.routing,
                        "model_id": o["model_id"],
                        "features": o["features"],
                        "success": o["success"],
                        "human": o.get("human"),
                    },
                )

    def decide(
        self,
        features: dict[str, str],
        harm_features: dict[str, str] | None = None,
        profile: dict[str, float] | None = None,
    ) -> str:
        """proceed/block/ask EU decision at a context (with the harm coordinate when available)."""
        assert self.waste is not None, "boot() must run before decide()"
        profile = profile or {}
        params: dict[str, Any] = {
            "model_id": self.waste["model_id"],
            "state_id": self.waste["state_id"],
            "features": features,
            "cost": profile.get("cost", UTILITY["cost"]),
            "aversion": profile.get("aversion", UTILITY["aversion"]),
            "interrupt_cost": profile.get("interrupt_cost", UTILITY["interrupt_cost"]),
        }
        if self.harm and harm_features:
            params["harm"] = {
                "model_id": self.harm["model_id"],
                "state_id": self.harm["state_id"],
                "features": harm_features,
                "harm_cost": profile.get("harm_cost", UTILITY["harm_cost"]),
            }
        return self._verb("structure_decide", params)["action"]

    def observe(self, features: dict[str, str], observation: int) -> None:
        """Learn one approve(1)/refuse(0) on the governance belief, in place."""
        assert self.waste is not None
        self._verb(
            "structure_observe",
            {
                "model_id": self.waste["model_id"],
                "state_id": self.waste["state_id"],
                "features": features,
                "observation": observation,
            },
        )

    def route(
        self,
        features: dict[str, str],
        roster: Any = None,
        profile: Any = None,
    ) -> dict[str, Any] | None:
        """The EU-max model for a request (None => inert — body keeps its model)."""
        if not self.routing:
            return None
        return self._verb(
            "routing_decide",
            {"routing_state_id": self.routing, "features": features, "roster": roster, "profile": profile},
        )

    def route_outcome(
        self,
        model_id: str,
        features: dict[str, str],
        success: bool,
        human: bool | None = None,
    ) -> None:
        """Learn from one routed turn's exec signal, in place."""
        if not self.routing:
            return
        self._verb(
            "routing_outcome",
            {
                "routing_state_id": self.routing,
                "model_id": model_id,
                "features": features,
                "success": success,
                "human": human,
            },
        )
