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


# The skin verbs the governor drives (decide/route/observe + boot). A wire-compatible
# engine (protocol major matches — the client re-checks that) can still predate one of
# these, so assert they're advertised at boot: the daemon then won't start (⇒ adapters
# fail open) instead of taking a first-decision 500.
_REQUIRED_VERBS = frozenset({
    "structure_bma", "structure_observe", "structure_decide",
    "routing_init", "routing_decide", "routing_outcome",
})


def _assert_engine_capable(info: dict[str, Any]) -> None:
    """Fail loud if the engine can't serve the verbs the governor drives.

    `initialize()` returns {version, protocol, methods}. Note the wire does NOT reveal the
    engine's git revision (version is a static "0.1.0"), so this is a capability check, not
    a freshness one — the reproducible "current version" guarantee is the digest-pinned
    DEFAULT_SKIN_IMAGE (see __init__.py).
    """
    methods = set(info.get("methods") or [])
    if not methods:
        raise RuntimeError(
            "credence engine advertised no methods on initialize() — not a compatible skin "
            "build. Pin a current image via CREDENCE_SKIN_IMAGE / CREDENCE_SKIN_COMMAND.")
    missing = _REQUIRED_VERBS - methods
    if missing:
        raise RuntimeError(
            f"credence engine is missing required verb(s) {sorted(missing)} (advertised "
            f"{len(methods)} methods) — update the engine image; the governor cannot govern "
            "without them.")


class BrainSession:
    def __init__(self, skin: Any, brain_dir: str, log: ObservationLog):
        self.skin = skin
        self.brain_dir = brain_dir
        self.log = log
        self.waste: dict[str, str] | None = None
        self.harm: dict[str, str] | None = None
        self.routing: str | None = None
        # {version, protocol, methods} from initialize(), for the boot banner/telemetry.
        self.engine: dict[str, Any] | None = None

    def _verb(self, method: str, params: dict[str, Any]) -> Any:
        return self.skin._call(method, params)

    def boot(self) -> None:
        """Build the server-side beliefs (warm-seeded), then replay the local log on top."""
        info = self.skin.initialize() or {}
        self.engine = {
            "version": info.get("version"),
            "protocol": info.get("protocol"),
            "methods": sorted(info.get("methods") or []),
        }
        _assert_engine_capable(info)

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
            # The counts file's contexts are positional tuples mapped against
            # config.HARM["feature_names"]; a column-order drift between the committed
            # brain and config would silently mis-map harm features into enforcement.
            # The artifact records its own feature_names (build_harm_brain) — assert they
            # agree. Loud at boot (daemon won't start ⇒ adapters fail open) beats a quiet
            # mis-map. CI's reproducibility test only guards this when the corpus is staged.
            brain_names = harm_counts.get("feature_names")
            if brain_names is not None and list(brain_names) != list(HARM["feature_names"]):
                raise ValueError(
                    f"harm brain feature_names {brain_names} != config.HARM {HARM['feature_names']}; "
                    "rebuild: python -m credence_governor_core.training.build_harm_brain <corpus> --out <brain>")
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
