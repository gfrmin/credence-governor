"""membrane.py — the proplang membrane adapter (HOSTS_PLAN boundary H,
section 2.7; membrane-wire.md in the proplang repo is the normative wire
statement).

A `BrainSession`-shaped session whose engine is the proplang
`proplang-govhost` binary driven over the MEMBRANE wire (JSON-lines on
stdio): the host publishes features, evidence, and an affordance menu;
one choice comes back per tick. The host sets NO priors — the engine's
prior is its alphabet (2^-dl over priced hypothesis programs); what
crosses the wire is world data only (namespace, guard grids, menu,
utility STEP TABLE) and per-tick scalars. Waste decision only in epoch
1 (HOSTS_PLAN 2.1): `observe_harm` is inert and `route` returns None —
the harm overlay and routing stay on the Julia engine.

Selection: `CREDENCE_MEMBRANE_COMMAND` (launch argv for the driver
binary, shlex-split), the exact analogue of `CREDENCE_SKIN_COMMAND`.
Deployment posture is SHADOW/DIFFERENTIAL first (the Julia engine stays
primary): see `training/membrane_diff.py` for the gate.

Conventions this adapter fixes (the as-built register, HOSTS_PLAN 8):

* one-hot encoding (2.4): each categorical feature/value pair becomes
  the indicator name `"<feature>=<value>" = 1.0`; absent names read 0.0
  engine-side (dormancy), so an unknown or schema-grown value simply
  emits nothing. Harm-tuple keys are projected OUT (8.6). 39 indicators
  + "t" = the declared 40-name namespace.
* the t-convention: `t` is the EVIDENCE-STREAM INDEX (the engine's hmm
  clock — one step per conditioned verdict), not wall time. A decision
  tick sends the CURRENT index (the slot the next verdict would fill);
  an evidence tick sends its own index and then advances it. Replay
  order == arrival order == live (8.2). This refines H-1's "original t
  re-sent": the BrainSession surface carries no event id, so the
  arrival-order clock IS the original t for every event whose verdict
  arrives in order — recorded for the increment report.
* menu order (R1, RULED at H's pack): `ask, block, proceed` — at exact
  indifference the engine's first-listed tie-break buys information.
  Ids are world-owned and stable: ask=3, block=2, proceed=1.
* the utility step table (2.6, membrane-wire.md 5): derived per tick
  from the profile-resolved constants, so per-request profiles are the
  wire's per-tick utility override. The think row is a dominated
  sentinel; if the driver honestly reports the internal act winning,
  this adapter maps it to its documented transport posture (fail-open
  proceed) with a warning.

Two utility generations (membrane-wire.md 6; `utility.form` is the
dispatch seam): `table@1` (above, the default) and `latent@1` — the
learned-utility wire, where the handshake declares a USay payload, the
theta_ask residual, the tau owner-response spec, a (dormant) tick-price
feature name and the affine gauge, all host-declared DATA whose
question→resolution→why register is docs/membrane-shadow.md. Under
latent@1 evidence is stream-tagged: a human verdict double-feeds (an
untagged world-report tick, then a "verdict" pointer tick — one event,
two disjoint agents, one clock step), grounded outcomes feed once per
event_id as "outcome" ticks (responder-free, doctrine O3), and the
warm corpus collapses to observe_counts pairs per context — the R-D23
DECLARED segmentation: collapse the fixed warm corpus, replay
everything else per-tick. Decision replies gain observability-only
readouts (residual_mean, sensitivity); this adapter stays a pure
choice-relay — readouts land in `last_readouts` for telemetry and are
NEVER branched on (HOSTS_PLAN 8.12(b): forking on them would re-create
host-side decision logic).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any, Callable, Iterator

from .config import GOVERNANCE, UTILITY

MEMBRANE_ENV = "CREDENCE_MEMBRANE_COMMAND"
WARM_CAP_ENV = "CREDENCE_MEMBRANE_WARM_CAP"

# R1 as ruled: ask, block, proceed — listing order is normative on the
# wire (argmaxEU ties resolve first-listed).
AFFORDANCES: list[tuple[str, int]] = [("ask", 3), ("block", 2), ("proceed", 1)]
MENU_IDS: list[int] = [aid for (_, aid) in AFFORDANCES]
_ID_TO_ACTION: dict[int, str] = {aid: name for (name, aid) in AFFORDANCES}


class MembraneError(RuntimeError):
    """An error reply from the membrane driver (e.g. impossible-evidence)."""


def indicator_names() -> list[str]:
    """The 39 one-hot indicator names, in config declaration order."""
    return [
        f"{name}={value}"
        for name, values in zip(GOVERNANCE["feature_names"], GOVERNANCE["feature_values"])
        for value in values
    ]


def onehot(features: dict[str, str]) -> dict[str, float]:
    """Project a categorical feature dict to declared waste indicators.

    Harm-tuple keys and undeclared values emit nothing (dormancy is
    free engine-side; the namespace is fixed at the handshake)."""
    out: dict[str, float] = {}
    for name, values in zip(GOVERNANCE["feature_names"], GOVERNANCE["feature_values"]):
        v = features.get(name)
        if v is not None and v in values:
            out[f"{name}={v}"] = 1.0
    return out


def utility_rows(profile: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """The step table from the profile-resolved constants (HOSTS_PLAN 2.6).

    Checks carried by the frozen proplang oracle: block beats proceed
    iff P(approve) < 1/(1+aversion) — the engine's declared threshold —
    and ask wins iff q < min(c(1-p), aversion*c*p), the myopic
    perfect-information VOI (its baked assumption is register item 8.4,
    measured by the differential gate, never tuned away)."""
    p = profile or {}
    c = float(p.get("cost", UTILITY["cost"]))
    lam = float(p.get("aversion", UTILITY["aversion"]))
    q = float(p.get("interrupt_cost", UTILITY["interrupt_cost"]))
    hc = float(p.get("harm_cost", UTILITY["harm_cost"]))
    sentinel = -(c + lam * c + hc + 1.0)
    return [
        {"fire": 3, "u": [-q, -q]},
        {"fire": 2, "u": [0.0, -lam * c]},
        {"fire": 1, "u": [-c, 0.0]},
        {"internal": "think", "u": [sentinel, sentinel]},
    ]


UTILITY_FORMS = ("table@1", "latent@1")


def latent_utility_decl() -> dict[str, Any]:
    """The governor's latent@1 utility declaration (membrane-wire.md
    6.1). Every value is host-declared DATA the wire reads as world
    data, never an engine constant; the per-choice register
    (question→resolution→why) is docs/membrane-shadow.md. The handshake
    test pins the emitted JSON, so any change here is a visible
    declaration change, not a silent knob.

    - said ["var",1]: utility = the learned pointer latent ū — the only
      coherent payload in the wire's implemented ["var",i] subset. That
      subset is action-degenerate (stop-report-2 §1: all terminal
      values move together), which grounds the stated field prediction
      recorded in docs/membrane-shadow.md.
    - theta_ask: the one residual (first position is charge-bearing —
      "theta_ask" prices ask decisions). Grid floor = the incumbent's
      own declared interrupt cost; ceiling = the d-close golden's.
      theta_bad is deliberately NOT declared: no affordance or
      comparison route exists to condition it (KSV non-identifiability).
    - tau: adopted verbatim from the d-close golden (declared, never
      updated — R-D9); no measured governor-side owner-noise source.
    - price "tick-price": a required name, deliberately DORMANT (no
      such feature is ever sent; absent reads 0) — no measured per-tick
      deliberation price exists, and sending a declared constant would
      smuggle it into the measured-price slot.
    - gauge: status-quo zero, usd scale (outcomes are dollar-priced).
    """
    return {
        "form": "latent@1",
        "said": ["var", 1],
        "residuals": [
            {"name": "theta_ask",
             "grid": [UTILITY["interrupt_cost"], 0.05, 0.1, 0.2, 0.4]},
        ],
        "tau": {"points": [0.5, 1, 2], "weights": [0.5, 0.3, 0.2]},
        "price": "tick-price",
        "gauge": {"zero": "status-quo", "scale": "usd"},
    }


def handshake_decl(utility_form: str = "table@1") -> dict[str, Any]:
    """The world declaration (membrane-wire.md section 2): 40-name
    namespace, singleton [0.5] guard grids per indicator, the three
    effectors as slot-free affordances in the R1-ruled order, the
    declared utility (the step table, or the latent@1 block), echo
    all-false (the epoch-1 restriction). The world block is identical
    across generations; only the utility value switches."""
    if utility_form == "latent@1":
        utility: dict[str, Any] = latent_utility_decl()
    elif utility_form == "table@1":
        utility = {"form": "table@1", "rows": utility_rows()}
    else:
        raise ValueError(f"unknown membrane utility form: {utility_form!r}")
    inds = indicator_names()
    return {
        "membrane": 1,
        "world": {
            "namespace": ["t"] + inds,
            "guards": [{"name": nm, "grid": [0.5]} for nm in inds],
            "menu": [
                {"id": aid, "name": name, "slots": []}
                for (name, aid) in AFFORDANCES
            ],
            "utility": utility,
            "echo": {
                "last_action": False,
                "tick": False,
                "ticks_spent_thinking": False,
            },
        },
    }


def flatten_warm_counts(counts: dict[str, Any]) -> Iterator[tuple[dict[str, str], int]]:
    """Warm counts -> pseudo-evidence ticks (HOSTS_PLAN 8.3): per
    context, n1 approvals then n0 refusals, contexts in file order —
    exact for the exchangeable families, a DECLARED approximation for
    the hmm families (their clock is the flattened index)."""
    names = counts.get("features") or GOVERNANCE["feature_names"]
    if list(names) != list(GOVERNANCE["feature_names"]):
        raise ValueError(
            f"warm counts feature names {names} != config GOVERNANCE "
            f"{GOVERNANCE['feature_names']}; refusing a silent mis-map")
    for ctx in counts.get("contexts", []):
        feats = dict(zip(GOVERNANCE["feature_names"], ctx["ctx"]))
        for _ in range(int(ctx.get("n1", 0))):
            yield feats, 1
        for _ in range(int(ctx.get("n0", 0))):
            yield feats, 0


class MembraneClient:
    """One line out, one line back — the transport half, injectable for
    tests (pass write_line/read_line callables) or spawned (`spawn`)."""

    def __init__(
        self,
        write_line: Callable[[str], None],
        read_line: Callable[[], str],
        shutdown: Callable[[], None] | None = None,
    ):
        self._write = write_line
        self._read = read_line
        self._shutdown = shutdown

    @classmethod
    def spawn(cls, argv: list[str], log: Callable[[str], None] = print) -> "MembraneClient":
        log(f"credence-governor: membrane engine = {' '.join(argv)}")
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        def write_line(s: str) -> None:
            assert proc.stdin is not None
            proc.stdin.write(s + "\n")
            proc.stdin.flush()

        def read_line() -> str:
            assert proc.stdout is not None
            line = proc.stdout.readline()
            if line == "":
                raise MembraneError("membrane driver closed the wire (EOF)")
            return line.rstrip("\n")

        def shutdown() -> None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        return cls(write_line, read_line, shutdown)

    @classmethod
    def from_env(cls, log: Callable[[str], None] = print) -> "MembraneClient":
        cmd = os.environ.get(MEMBRANE_ENV)
        if not cmd:
            raise RuntimeError(
                f"no membrane engine: set {MEMBRANE_ENV} to the "
                "proplang-govhost launch argv")
        return cls.spawn(shlex.split(cmd), log)

    def request(self, obj: dict[str, Any]) -> dict[str, Any]:
        self._write(json.dumps(obj))
        reply = json.loads(self._read())
        if not isinstance(reply, dict):
            raise MembraneError(f"malformed reply: {reply!r}")
        return reply

    def shutdown(self) -> None:
        if self._shutdown is not None:
            self._shutdown()


def _read_counts(brain_dir: str, file: str) -> Any | None:
    p = os.path.join(brain_dir, file)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class MembraneSession:
    """The `BrainSession` surface over the membrane wire (epoch 1:
    waste only; harm and routing inert). Holds no probability and does
    no arithmetic on one — Invariant 1 as before, narrower pipe."""

    def __init__(self, client: MembraneClient, brain_dir: str, log: Any,
                 logline: Callable[[str], None] = print,
                 utility_form: str = "table@1"):
        if utility_form not in UTILITY_FORMS:
            raise ValueError(f"unknown membrane utility form: {utility_form!r}")
        self.client = client
        self.brain_dir = brain_dir
        self.log = log
        self.logline = logline
        self.utility_form = utility_form
        # BrainSession-parity attributes (consumers poke these for telemetry)
        self.waste: dict[str, str] | None = None
        self.harm: dict[str, str] | None = None
        self.routing: str | None = None
        self.engine: dict[str, Any] | None = None
        self.caps: frozenset[str] = frozenset()
        self.tail: dict[str, str] | None = None
        # the evidence-stream index (the t-convention; module docstring)
        self._t = 0
        # the last decision reply's scalar readouts (p1, entropy_bits, and on
        # latent@1 residual_mean/sensitivity) — OBSERVABILITY ONLY, copied by
        # the shadow's record writer, never read by any decide path here.
        self.last_readouts: dict[str, Any] = {}
        # outcome dedup: at most one "outcome" tick per event_id, spanning
        # boot replay and live submits (the session-held seen-set).
        self._seen_outcomes: set[str] = set()

    @property
    def _latent(self) -> bool:
        return self.utility_form == "latent@1"

    def supports(self, verb: str) -> bool:
        return verb in self.caps

    def boot(self) -> None:
        reply = self.client.request(handshake_decl(self.utility_form))
        if not reply.get("ok"):
            raise MembraneError(f"handshake refused: {reply!r}")
        self.engine = {
            "version": "proplang-govhost",
            "protocol": f"membrane/{reply.get('proto')}",
            "methods": ["tick"],
            "models": reply.get("models"),
            "namespace_bits": reply.get("namespace_bits"),
            "utility_form": self.utility_form,
        }
        if "ulatents" in reply:
            self.engine["ulatents"] = reply["ulatents"]
        self.waste = {"model_id": "membrane", "state_id": "membrane"}
        counts = _read_counts(self.brain_dir, GOVERNANCE["warm_counts_file"])
        if self._latent:
            # the fixed warm corpus COLLAPSES to observe_counts pairs per
            # context (R-D23 declared segmentation; milliseconds instead of
            # the row replay's minutes). The warm cap is a row-replay knob
            # and does not apply to the counts path.
            if counts:
                n_ctx = self._warm_counts_collapsed(counts)
                self.logline(
                    f"credence-governor: membrane warm collapse {n_ctx} "
                    "contexts (observe_counts)")
        elif counts:
            # warm counts -> pseudo-evidence ticks; the cap is an ADAPTER
            # knob (HOSTS_PLAN 2.5), never an engine constant. -1 = all.
            cap = int(os.environ.get(WARM_CAP_ENV, "-1"))
            fed = 0
            for feats, obs in flatten_warm_counts(counts):
                if 0 <= cap <= fed:
                    break
                self.observe(feats, obs)
                fed += 1
            self.logline(
                f"credence-governor: membrane warm replay {fed} ticks"
                + (f" (cap {cap})" if cap >= 0 else ""))
        # the local observation log on top: verdict history in arrival
        # order (8.2), then — latent only — outcome history in arrival
        # order. That two-segment order is the DECLARED boot segmentation
        # (docs/membrane-shadow.md); exchangeable families are order-free,
        # the hmm clock reads it as the declared flattening approximation.
        for ctx in self.log.replay_contexts():
            self.observe(ctx["features"], ctx["observation"])
        if self._latent:
            for oc in self.log.replay_outcome_contexts():
                self.observe_outcome(oc["event_id"], oc["features"], oc["good"])

    def _tick(self, msg: dict[str, Any]) -> dict[str, Any]:
        reply = self.client.request({"tick": msg})
        if "error" in reply:
            raise MembraneError(str(reply["error"]))
        return reply

    def _counts(self, msg: dict[str, Any]) -> dict[str, Any]:
        reply = self.client.request({"observe_counts": msg})
        if "error" in reply:
            raise MembraneError(str(reply["error"]))
        return reply

    def _warm_counts_collapsed(self, counts: dict[str, Any]) -> int:
        """Feed the fixed warm corpus as observe_counts collapses
        (membrane-wire.md 6.3): per context in file order, one untagged
        line (world report role) then one "verdict" line (pointer role),
        both at the same t, the clock advancing by the context's
        evidence mass — the same double-feed rule the live verdict path
        applies, collapsed. Refuses a feature-name mismatch exactly as
        flatten_warm_counts does."""
        names = counts.get("features") or GOVERNANCE["feature_names"]
        if list(names) != list(GOVERNANCE["feature_names"]):
            raise ValueError(
                f"warm counts feature names {names} != config GOVERNANCE "
                f"{GOVERNANCE['feature_names']}; refusing a silent mis-map")
        n_ctx = 0
        for ctx in counts.get("contexts", []):
            n1, n0 = int(ctx.get("n1", 0)), int(ctx.get("n0", 0))
            if n1 == 0 and n0 == 0:
                continue
            feats = onehot(dict(zip(GOVERNANCE["feature_names"], ctx["ctx"])))
            feats["t"] = float(self._t)
            payload = {"features": feats, "counts": {"1": n1, "0": n0}}
            self._counts(dict(payload))
            self._counts({"stream": "verdict", **payload})
            self._t += n1 + n0
            n_ctx += 1
        return n_ctx

    def decide(
        self,
        features: dict[str, str],
        harm_features: dict[str, str] | None = None,
        profile: dict[str, float] | None = None,
        tail_features: dict[str, str] | None = None,
    ) -> str:
        """proceed/block/ask at a context. Epoch 1 is waste-only: the
        harm and tail coordinates are accepted for surface parity and
        deliberately unused (HOSTS_PLAN 2.1). On latent@1 the profile is
        also unused: per-tick utility is a table@1 concept (the v2 tick
        parser drops unknown keys, so sending one would be silently
        ignored — we don't)."""
        del harm_features, tail_features  # epoch-1 scope cut, documented
        feats = onehot(features)
        feats["t"] = float(self._t)
        msg: dict[str, Any] = {"features": feats, "menu": MENU_IDS}
        if not self._latent:
            msg["utility"] = {"form": "table@1", "rows": utility_rows(profile)}
        reply = self._tick(msg)
        # observability only — the choice relay below never reads these
        self.last_readouts = {k: v for k, v in reply.items() if k != "choice"}
        choice = reply.get("choice") or {}
        if "fire" in choice:
            aid = int(choice["fire"])
            action = _ID_TO_ACTION.get(aid)
            if action is None:
                raise MembraneError(f"undeclared affordance in reply: {aid}")
            return action
        # the driver reports the internal act honestly; the adapter's
        # documented transport posture is fail-open
        self.logline(
            "credence-governor: membrane chose think; fail-open => proceed")
        return "proceed"

    def observe(self, features: dict[str, str], observation: int) -> None:
        """Learn one approve(1)/refuse(0): the judged event's features
        re-sent with the verdict; the evidence clock advances. On
        latent@1 one human verdict DOUBLE-FEEDS (the host rule,
        docs/membrane-shadow.md): an untagged tick (world report role —
        P(approve|X) keeps learning, v1 continuity) then a "verdict"
        tick (owner-response role — the pointer through tau). Two
        disjoint agents, one event, one clock step."""
        feats = onehot(features)
        feats["t"] = float(self._t)
        ev = int(observation)
        self._tick({"features": feats, "evidence": ev})
        if self._latent:
            self._tick({"stream": "verdict", "features": feats, "evidence": ev})
        self._t += 1

    def observe_outcome(self, event_id: str, features: dict[str, str],
                        good: int) -> None:
        """Latent-only outcome evidence (stream "outcome" — the
        responder-free primary evidence, doctrine O3): the judged
        event's decide-time features re-sent with the grounded good-bit
        (1 kept/completed, 0 reverted; ambiguous never reaches here).
        At most ONE outcome tick per event_id — the seen-set spans boot
        replay and live submits. Inert on table@1 (epoch-1 has no
        outcome channel)."""
        if not self._latent or event_id in self._seen_outcomes:
            return
        self._seen_outcomes.add(event_id)
        feats = onehot(features)
        feats["t"] = float(self._t)
        self._tick({"stream": "outcome", "features": feats, "evidence": int(good)})
        self._t += 1

    def observe_harm(self, features: dict[str, str], unsafe: int) -> None:
        """Inert in epoch 1 (the harm overlay stays on the Julia
        engine); the verdict is preserved in the observation log, so
        nothing is lost for the epoch that picks it up."""
        del features, unsafe

    def route(self, features: dict[str, str], roster: Any = None,
              profile: Any = None) -> dict[str, Any] | None:
        """Inert in epoch 1 (routing stays on the Julia engine)."""
        del features, roster, profile
        return None

    def route_outcome(self, model_id: str, features: dict[str, str],
                      success: bool, human: bool | None = None) -> None:
        del model_id, features, success, human


def build_membrane_session(
    brain_dir: str, log: Any, logline: Callable[[str], None] = print,
    utility_form: str = "table@1",
) -> MembraneSession:
    """Resolve the membrane engine from CREDENCE_MEMBRANE_COMMAND and
    wrap it in the BrainSession-shaped adapter (unbooted)."""
    return MembraneSession(
        MembraneClient.from_env(logline), brain_dir, log, logline,
        utility_form=utility_form)
