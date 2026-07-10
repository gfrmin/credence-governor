"""daemon.py — the governor HTTP surface + sensor dispatch. Holds only opaque skin
handles; every decision is an engine verb. Mirrors the credence-openclaw TS daemon's
non-negotiable order (sense -> decide/learn over the wire -> emit), adding a
synchronous `POST /decide` for subprocess-hook adapters (Claude Code) alongside the
SSE `POST /sensor` + `GET /signals` used by in-process plugins (OpenClaw).

Feature extraction is SERVER-SIDE here (extract once): an adapter may POST a
pre-extracted `features` dict, OR post a normalized AgentToolEvent+Session and the
daemon extracts. Fail-open: any per-event error is logged and the request still
acks/returns proceed.

stdlib http.server + ThreadingHTTPServer; a single lock serialises engine calls
(the skin is one stdio pipe / one belief — one request at a time).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable

from .config import HARM
from .features import extract_features
from .capture import RawCaptureLog
from .log import ObservationLog
from .safety import extract_harm
from .schema import event_and_session_from_payload
from .session import BrainSession
from .shadow import MembraneShadow


def data_dir() -> str:
    """Absolute path to the bundled governance data (bdsl/, brain/, profiles/)."""
    return str(resources.files("credence_governor_core") / "data")


def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# An `outcome` record links a MEASURED observable back to the decide-time decision it
# followed (by in_response_to == the tool-proposed event_id). Every field is nullable and
# several outcome records may share one event_id (a result-time record first, a grounding
# backfill later). NON-CAUSAL like capture: outcomes are telemetry the report tallies, never
# replayed into a belief (log.replay_* filter by event_type, so an `outcome` type is
# replay-inert by construction). The fields are measured, never a good/bad judgement.
_OUTCOME_FIELDS = ("completed", "latency_s", "spend_usd", "reverted", "retries", "error")


def _outcome_record(in_response_to: str | None, source: str, **fields: Any) -> dict[str, Any]:
    """One outcome record: the fixed shape with every observable defaulting to None, the
    caller overriding only what it measured. Unknown keys are dropped (a typo can't smuggle
    a field onto the record)."""
    record: dict[str, Any] = {"event_type": "outcome", "in_response_to": in_response_to, "source": source}
    for name in _OUTCOME_FIELDS:
        record[name] = fields.get(name)
    return record


def _ask_text(proposed: Any, rationale: str | None = None) -> str:
    tool = str((proposed or {}).get("tool_name") or (proposed or {}).get("tool") or "(unknown)")
    inp = (proposed or {}).get("input")
    s = "(none)" if inp is None else json.dumps(inp)
    if len(s) > 80:
        s = s[:80] + "…"
    base = f"Allow `{tool}` to run with input `{s}`?"
    return f"{base} — {rationale}" if rationale else base


# A block is "safety" (hard deny, no override offered) iff an ATTACK-PATTERN feature is hot:
# tainted data flowing to an EXTERNAL target, a credential-exfil chain, or an injected
# imperative. These are the "the agent may be acting against the user" signals.
#
# We deliberately do NOT treat `taint-flow == "tainted-sink"` as safety. tainted-sink only
# means "a token the agent saw earlier reappears in the args of a write/edit/exec" — which
# is ordinary coding (read a config, then write a derived file; see a path, then edit it).
# It is not evidence of adversarial intent; only flow to an *external* recipient
# (tainted-external-target) crosses the trust boundary. Hard-denying every tainted-sink made
# benign local ops (editing a file you just read, POSTing to 127.0.0.1, reading your own log)
# unrecoverable in enforce mode. So tainted-sink falls through to "waste" (overridable).
#
# We also do NOT key on `action-class` (delete/exec/external-send): that's the action *type*,
# not the block's *motivation* — a repeated `rm` flagged as a waste loop must stay OVERRIDABLE,
# not be hard-denied for being destructive. Deterministic feature inspection, no belief
# arithmetic — so it lives here (server-side), not in the thin adapter (Invariant 1).
#
# M4: the hard/soft split reads `taint-source` (M2 provenance), the dual of the posterior
# learning to discount own-sourced taint. An injected-imperative or external-target taint
# whose value came from the agent's OWN footprint (read-own/command-own/local-own) is benign
# provenance — editing security code you just read, not an attacker channel — so it is NOT a
# hard safety deny. `cred-exfil-chain` is structural (a credential-read → external-send chain)
# and stays hot regardless of provenance.
#
# This is a deliberate recall TRADE, not free: an *unmarked* injection committed into the
# agent's own workspace and then read is `read-own` and gets downgraded too. Two things bound
# the exposure: (a) explicitly injection-shaped content is classed `marker` (safety.looks_untrusted),
# which is NOT an OWN class and stays hot regardless of locality; (b) the downgrade is hard-deny
# → overridable ASK, never a silent allow — the user still sees it. The keyword-marker coverage
# is the recall floor here; widen looks_untrusted before relying on this for stronger threats.
_OWN_SOURCES = {"read-own", "command-own", "local-own"}

# Coding enforcement (docs/coding-threat-matched-harm-model.md). The shipped hard-deny
# path above is assistant-tool-shaped — tainted-external-target / cred-exfil-chain /
# external-send all key on a dedicated send TOOL name, but coding exfil routes through
# bash, so it hard-denied 0% of the red-team's coding attacks even though provenance
# resolved (taint-source=web). These rules consult the coding-threat features (now part
# of the conditioned 7-tuple, safety.extract_harm) so the hard-vs-overridable split sees
# the coding shape. P-independent: deterministic feature inspection, no belief/EU
# arithmetic — `_block_category` only LABELS a block (the EU decision still selects
# block/ask/proceed), so this can only upgrade an overridable block to a hard deny when
# the attack signature is present; it never spuriously blocks, never raises benign-coding
# hard-FP, never removes the host's own safety. When a caller passes only the shipped 6
# (no coding-threat keys), every `.get` defaults out — the rule is inert and behaviour is
# the pre-coding split. (M4 promoted these same features INTO the posterior, so the EU
# decision now also blocks self-driven coding exfil the label alone could not escalate.)
#
# Two coding rules, mirroring the existing motivation split:
#   - exfil: data leaving to an UNKNOWN external host is hard regardless of who drove
#     it (an external-send/credential-access whose egress is external-unknown).
#   - attacker-driven: a consequential action (sensitive target, or a destructive /
#     privilege / package-mutation op) under EXTERNAL provenance — an untrusted source
#     steered it. A SELF-driven consequential op stays an overridable ask (the agent's
#     own rm / sensitive write is friction-worthy, not an adversarial-intent hard deny).
_HOT_SENSITIVITY = {"system-privileged", "credential-store", "project-config"}
_HOT_CODING_ACTION = {"destructive", "privilege-op", "package-mutation"}
# CONFIRMED-external provenance: source classes that are genuinely untrusted (web /
# email / fetched markers / *-external), as opposed to the *-unknown classes
# (indeterminate locality — a read whose target couldn't be placed) or *-own (the
# agent's own footprint). The hard rules gate on CONFIRMED external: treating
# unknown-locality as attacker provenance hard-denied benign coding at scale (real
# reads resolve to *-unknown whenever trusted_paths is unset, which is the common case),
# while the genuine injection signal always carries a confirmed-external source.
_EXTERNAL_SOURCES = {
    "web", "browser", "email", "message", "command-network", "marker",
    "read-external", "command-external", "local-external",
}


def _block_category(features: dict[str, str]) -> str:
    src = features.get("taint-source", "none")
    own = src in _OWN_SOURCES
    # Confirmed-external provenance — genuinely untrusted, as opposed to *-unknown
    # (indeterminate locality) or *-own. attacker_driven needs this stronger bar (see below).
    external_prov = src in _EXTERNAL_SOURCES
    injection = (
        features.get("taint-flow", "none") == "tainted-external-target"
        or features.get("injected-imperative", "no") == "yes"
    )
    # injection hard-denies when NOT own-sourced (the M3 threshold, live-verified): an
    # injected imperative / external-target taint from anything but the agent's own
    # footprint is an attacker channel. cred-exfil-chain is structural and stays hot.
    hot = features.get("cred-exfil-chain", "no") == "yes" or (injection and not own)

    # Coding rules (inert when the coding-threat features are absent).
    external_egress = features.get("egress-destination", "none") == "external-unknown"
    coding_action = features.get("coding-action-class", "other")
    sensitivity = features.get("target-sensitivity", "none")
    # exfil: CREDENTIAL-store data leaving to an unknown external host, regardless of who
    # drove it. A plain external-send to an external host (a benign API curl, a `gh api`,
    # a `docker compose` pull) is NOT exfil — the credential involvement is what makes the
    # egress adversarial. Keyed on the credential signal, not the bare external-send.
    exfil = external_egress and (
        coding_action == "credential-access" or sensitivity == "credential-store"
    )
    # attacker-driven: an untrusted source steered a consequential action (sensitive
    # target, or a destructive / privilege / package-mutation op). Gated on CONFIRMED
    # external provenance — *-unknown locality (a read that couldn't be placed, the common
    # case when trusted_paths is unset) is NOT evidence of steering, and treating it as
    # such hard-denied benign coding (rm of a scratch file, `gh api .../package.json`) en
    # masse. Self-driven and unknown-provenance consequential ops stay overridable asks.
    attacker_driven = external_prov and (
        sensitivity in _HOT_SENSITIVITY or coding_action in _HOT_CODING_ACTION
    )
    hot = hot or exfil or attacker_driven
    return "safety" if hot else "waste"


# Human-readable phrases for the structural coordinates a rationale names.
_SENSITIVITY_PHRASE = {
    "credential-store": "a credential store (.env, keys, .aws/…)",
    "system-privileged": "a privileged system path (~/.ssh, /etc, cron…)",
    "project-config": "CI/deploy config (workflows, Dockerfile, lockfiles)",
}
_ACTION_PHRASE = {
    "destructive": "a destructive op (rm / reset --hard / DROP…)",
    "privilege-op": "a privilege op (sudo / chmod +s…)",
    "package-mutation": "a package/dependency mutation",
    "credential-access": "a credential read",
}


def _rationale(features: dict[str, str], category: str) -> str:
    """A specific, structural "why" for a gated call — the coordinates that made it safety- or
    waste-shaped. Deterministic feature inspection (like _block_category, Invariant 1): the point
    is that an override lands against a STATED reason, not a black box, which is what makes it a
    trustworthy calibration signal for the harm belief (A2). It names the dominant hot
    coordinate(s) — usually, but not always, the label's exact motivation. It is ADVISORY
    (legibility only): the gate and the harm-gating both use _block_category, never this string."""
    src = features.get("taint-source", "none")
    own = src in _OWN_SOURCES
    external_prov = src in _EXTERNAL_SOURCES
    injected = (
        features.get("injected-imperative", "no") == "yes"
        or features.get("taint-flow", "none") == "tainted-external-target"
    )
    sensitivity = features.get("target-sensitivity", "none")
    action = features.get("coding-action-class", "other")
    egress_ext = features.get("egress-destination", "none") == "external-unknown"

    reasons: list[str] = []
    if features.get("cred-exfil-chain", "no") == "yes" or (
        egress_ext and (action == "credential-access" or sensitivity == "credential-store")
    ):
        reasons.append("reads a credential store and sends it to an unknown external host")
    if injected and not own:
        reasons.append("acts on an instruction from untrusted fetched content")
    if external_prov and sensitivity in _HOT_SENSITIVITY:
        reasons.append(
            f"an untrusted source steered a change to {_SENSITIVITY_PHRASE.get(sensitivity, sensitivity)}"
        )
    elif sensitivity in _SENSITIVITY_PHRASE:
        reasons.append(f"touches {_SENSITIVITY_PHRASE[sensitivity]}")
    if action in _ACTION_PHRASE and not reasons:
        reasons.append(_ACTION_PHRASE[action])
    if reasons:
        return "; ".join(dict.fromkeys(reasons))
    if features.get("recent-identical-call-count", "ident-0") != "ident-0":
        return "a repeated identical call (possible loop)"
    return "flagged as likely unsafe" if category == "safety" else "flagged as low-value / a possible loop"


def _harm_cell(features: dict[str, str]) -> tuple[str, ...]:
    """The 7-tuple harm context (the belief's cell), for per-cell burst dedup of harm-learning."""
    return tuple(features.get(n, "") for n in HARM["feature_names"])


def _action_signal(action: str, proposed: Any, rationale: str | None = None) -> dict[str, Any]:
    if action == "ask":
        return {"effector": "ask", "parameters": {"text": _ask_text(proposed, rationale)}}
    if action == "block":
        reason = f"credence-governor: {rationale}" if rationale else "Refused based on prior approval observations."
        return {"effector": "block", "parameters": {"reason": reason}}
    return {"effector": "proceed", "parameters": {}}


class Daemon:
    def __init__(
        self,
        session: BrainSession,
        log: ObservationLog,
        engine_lock: threading.Lock,
        logline: Callable[[str], None] = lambda m: None,
        capture: RawCaptureLog | None = None,
        shadow: MembraneShadow | None = None,
    ):
        self.session = session
        self.log = log
        self.lock = engine_lock
        self.logline = logline
        # Opt-in raw-event capture (None when disabled). Non-causal — a re-extractable
        # training corpus, never read back into a belief.
        self.capture = capture
        # The membrane shadow (None when disabled): every decide/verdict/outcome
        # is mirrored to it AFTER the primary path completes its own work. Its
        # submit_* surface is enqueue-only and never raises by contract; the
        # _shadow_* wrappers below add defense-in-depth, because an escaped
        # exception here would be caught by the handler's fail-open and flip an
        # already-computed block/ask into proceed.
        self.shadow = shadow
        # decide-time features by event_id, bounded — the hot-path source for
        # the shadow's outcome joins (/result fires per tool call; re-reading
        # the whole log there would be O(log) per call). Misses (e.g. an
        # outcome for a pre-restart event) fall back to the log read.
        self._recent_features: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._feat_cache_lock = threading.Lock()
        # Set once the engine has booted. The server binds + serves BEFORE boot (so a
        # duplicate daemon fails fast on EADDRINUSE instead of booting a second engine);
        # until this flips, /ready, /decide and /sensor answer a fast 503 (fail-open),
        # not a hang. See run() and the handler's ready-gate.
        self.ready = threading.Event()
        self._subscribers: set[queue.Queue] = set()
        self._subs_lock = threading.Lock()
        self._pending_asks: dict[str, dict[str, str]] = {}
        self._pending_routes: dict[str, dict[str, Any]] = {}

    # ── feature extraction (server-side, single-source) ──
    def features_for(self, payload: dict[str, Any]) -> dict[str, str]:
        feats = payload.get("features")
        if feats is not None:
            return feats
        event, session = event_and_session_from_payload(payload)
        # extract_harm is the conditioned harm 7-tuple (coding-threat features merged
        # with the shipped safety signals) — the SAME projection build_harm_brain trains
        # on (train==runtime). It also carries everything `_block_category` reads, so the
        # hard-vs-overridable LABEL needs no separate enforcement pass (M4 absorbed M3's
        # `_enforcement_view`): one extraction feeds the posterior AND the label.
        return {**extract_features(event, session), **extract_harm(event, session)}

    # ── the shadow mirror (telemetry-only; never touches the response path) ──
    def _remember_features(self, event_id: str, features: dict[str, str]) -> None:
        with self._feat_cache_lock:
            self._recent_features[event_id] = features
            while len(self._recent_features) > 4096:
                self._recent_features.popitem(last=False)

    def _shadow_decide(self, event_id: str, features: dict[str, str],
                       profile: dict[str, float] | None) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.submit_decide(event_id, features, profile)
        except Exception as err:  # noqa: BLE001 — shadow telemetry must never break a decision
            self.logline(f"credence-governor: shadow decide mirror failed (non-fatal): {err}")

    def _shadow_verdict(self, features: dict[str, str], obs: int) -> None:
        """Mirror one WASTE verdict. harm_observation is never forwarded —
        epoch 1 keeps harm on the Julia engine (the shadow's observe_harm is
        inert anyway)."""
        if self.shadow is None:
            return
        try:
            self.shadow.submit_verdict(features, obs)
        except Exception as err:  # noqa: BLE001
            self.logline(f"credence-governor: shadow verdict mirror failed (non-fatal): {err}")

    def _shadow_outcome(self, record: dict[str, Any]) -> None:
        """Mirror one just-written outcome record as outcome evidence: the
        good-bit rule (0 iff reverted, 1 iff completed and not reverted,
        skip otherwise — ambiguous is not evidence), features joined from
        the decide-time cache with the log read as the miss fallback."""
        if self.shadow is None:
            return
        try:
            eid = record.get("in_response_to")
            if not isinstance(eid, str) or not eid:
                return
            good = ObservationLog._outcome_good_bit(record)
            if good is None:
                return
            with self._feat_cache_lock:
                features = self._recent_features.get(eid)
            if features is None:
                features = self._features_for_event(eid)
            if features is None:
                return
            self.shadow.submit_outcome(eid, features, good)
        except Exception as err:  # noqa: BLE001
            self.logline(f"credence-governor: shadow outcome mirror failed (non-fatal): {err}")

    # ── SSE ──
    def _emit(self, signal: dict[str, Any]) -> None:
        frame = f"data: {json.dumps(signal)}\n\n"
        with self._subs_lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(frame)

    def _emit_decision(self, in_response_to: str, action: str, proposed: Any, rationale: str | None = None) -> None:
        self.log.append({"event_type": "decision", "in_response_to": in_response_to, "action": action})
        eff = _action_signal(action, proposed, rationale)
        self._emit(
            {
                "signal_type": "effector",
                "signal_id": _short_id("sig"),
                "in_response_to": in_response_to,
                "effector": eff["effector"],
                "parameters": eff["parameters"],
            }
        )

    # ── the synchronous decision (hook adapters) ──
    def decide_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        features = self.features_for(payload)
        event_id = str(payload.get("event_id") or _short_id("evt"))
        with self.lock:
            action = self.session.decide(features, features, payload.get("profile"))
        self.log.append({"event_type": "tool-proposed", "event_id": event_id,
                         "features": features, "ts": round(time.time(), 3)})
        self.log.append({"event_type": "decision", "in_response_to": event_id, "action": action})
        # shadow AFTER the appends (the membrane-shadow record's join target
        # exists) — enqueue-only, never in the response path.
        self._remember_features(event_id, features)
        self._shadow_decide(event_id, features, payload.get("profile"))
        # Capture the raw payload (when enabled) so a future extractor re-derives features
        # over this real traffic. Best-effort and absolutely non-fatal: this runs AFTER the
        # decision is computed, so ANY capture exception (not just OSError — a deeply nested
        # payload could RecursionError, a non-serialisable input could TypeError) must be
        # swallowed here. If it escaped, the outer handler's fail-open would turn the
        # already-computed block/ask into proceed — a capture hiccup must never do that.
        if self.capture is not None and payload.get("features") is None:
            try:
                self.capture.append(event_id, payload)
            except Exception as err:  # noqa: BLE001 — telemetry must never break a decision
                self.logline(f"credence-governor: raw capture failed (non-fatal): {err}")
        category = _block_category(features)
        rationale = _rationale(features, category)
        return {"action": action, "features": features, "event_id": event_id,
                "category": category, "rationale": rationale}

    # ── result-time outcome capture (the decide-time decision's measured aftermath) ──
    def _governance_event_ids(self) -> set[str]:
        """Every event_id the governor actually decided on (a logged tool-proposed) — the
        set an outcome may legitimately link back to."""
        return {
            r["event_id"]
            for r in self.log.read()
            if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str)
        }

    def _last_outcome_pending_event_id(self) -> str | None:
        """The most recent gated call that has no outcome record yet — the fallback the result
        hook resolves to when it cannot name the event_id itself (mirrors _last_gated_event_id's
        read-the-log pattern). Most recent wins; a call already carrying an outcome is skipped so
        a burst of results does not all collapse onto the last proposal."""
        records = self.log.read()
        answered = {
            str(r.get("in_response_to"))
            for r in records
            if r.get("event_type") == "outcome" and r.get("in_response_to")
        }
        pending: str | None = None
        for r in records:
            if r.get("event_type") == "tool-proposed" and isinstance(r.get("event_id"), str):
                if r["event_id"] not in answered:
                    pending = r["event_id"]
        return pending

    def result_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a result-time outcome for a past decision. The caller names the event_id
        explicitly, or we fall back to the most recent still-unanswered proposal. Append-only
        telemetry (no engine, no lock): safe during boot, replay-inert. Multiple outcomes per
        event_id are allowed (this result-time record plus a later grounding backfill)."""
        event_id = payload.get("event_id") or self._last_outcome_pending_event_id()
        record = _outcome_record(
            event_id, "result-hook",
            completed=payload.get("completed"),
            latency_s=payload.get("latency_s"),
            spend_usd=payload.get("spend_usd"),
            reverted=payload.get("reverted"),
            retries=payload.get("retries"),
            error=payload.get("error"),
        )
        self.log.append(record)
        self._shadow_outcome(record)
        return {"ok": True, "event_id": event_id}

    # ── explicit human feedback (Claude Code has no onResolution; close the loop here) ──
    def _features_for_event(self, event_id: str) -> dict[str, str] | None:
        """Recover the features logged at decide-time for a past event. The sync /decide
        path logs tool-proposed{event_id, features}; the SSE path's in-memory _pending_asks
        is not populated for hooks, so we read the log. Most recent match wins."""
        feats: dict[str, str] | None = None
        for r in self.log.read():
            if r.get("event_type") == "tool-proposed" and r.get("event_id") == event_id and r.get("features"):
                feats = r["features"]
        return feats

    def _last_gated_event_id(self) -> str | None:
        """The most recent decision the governor actually GATED (block/ask) — what a user
        means by "correct the last decision" (a proceed never interrupted them, so it should
        not be shadowed in front of the block that did). Falls back to the last proposed
        event if nothing was gated."""
        gated: str | None = None
        last_proposed: str | None = None
        for r in self.log.read():
            et = r.get("event_type")
            if et == "tool-proposed" and isinstance(r.get("event_id"), str):
                last_proposed = r["event_id"]
            elif et == "decision" and r.get("action") in ("block", "ask") and isinstance(r.get("in_response_to"), str):
                gated = r["in_response_to"]
        return gated or last_proposed

    def feedback(self, event_id: str | None, observation: int) -> dict[str, Any]:
        """Record a human verdict on a past decision and condition the beliefs — the Claude Code
        analogue of OpenClaw's onResolution → user-responded → observe. event_id None => the most
        recent gated decision. The appended user-responded record is exactly what boot's replay
        re-applies (governance always; harm only when it carries a harm_observation), so the
        correction survives a restart (order-independent => exact). A verdict on a SAFETY-category
        gate also teaches the harm overlay (see _plan_verdict)."""
        eid = event_id or self._last_gated_event_id()
        if not eid:
            return {"ok": False, "error": "no decision on record to correct"}
        features = self._features_for_event(eid)
        if features is None:
            return {"ok": False, "error": f"unknown event_id {eid}"}
        obs = 1 if observation else 0
        extra = self._plan_verdict(features, obs)
        self.log.append(
            {"event_type": "user-responded", "in_response_to": eid,
             "response": "yes" if obs else "no", "human": True, **extra}
        )
        with self.lock:
            self._condition_verdict(features, obs, extra)
        return {"ok": True, "event_id": eid, "observation": obs,
                "category": extra["category"], "harm_observation": extra.get("harm_observation")}

    # ── one human verdict → beliefs (shared by /feedback and the SSE user-responded path) ──
    def _plan_verdict(self, features: dict[str, str], obs: int) -> dict[str, Any]:
        """The audit + replay fields for one verdict, WITHOUT touching beliefs (so it can run
        outside the engine lock; it only reads the log, for the burst-dedup check). The waste
        belief always learns (the general approve/refuse posterior); the harm overlay learns only
        on a SAFETY-category gate, with INVERSE polarity (harm_obs = 1 − obs: approving is
        "safe"→0, rejecting is "unsafe"→1), rate-bounded by per-cell burst dedup. A
        `harm_observation` field marks a verdict that WILL be conditioned (and replayed on boot);
        `harm_deduped` is a burst repeat — audited only, never conditioned or replayed."""
        category = _block_category(features)
        extra: dict[str, Any] = {"category": category, "rationale_shown": _rationale(features, category)}
        if category == "safety":
            verdict = 1 - obs
            if self._harm_burst_duplicate(features, verdict):
                extra["harm_deduped"] = verdict
            else:
                extra["harm_observation"] = verdict
        return extra

    def _condition_verdict(self, features: dict[str, str], obs: int, extra: dict[str, Any]) -> None:
        """Apply one verdict to the beliefs (engine lock held) — the exact operations boot's
        replay re-applies, so live == replay. Waste always; harm only when _plan_verdict marked a
        (non-deduped) harm_observation."""
        self.session.observe(features, obs)
        if extra.get("harm_observation") is not None:
            self.session.observe_harm(features, int(extra["harm_observation"]))
        # mirror the WASTE verdict only (epoch 1: harm never reaches the shadow)
        self._shadow_verdict(features, obs)

    def _harm_burst_duplicate(self, features: dict[str, str], verdict: int) -> bool:
        """True if the most recent CONDITIONED harm-observation on this exact harm-cell had the
        same verdict — a repeat of this cell's last verdict (a burst), audited but not stacked
        (an intervening OTHER-cell verdict does not break it). Bounds the RATE of
        drift a burst of identical overrides can cause; the DIRECTION a consistently-miscalibrated
        operator induces is the OFFLINE audit's job, not this online rule's."""
        cell = _harm_cell(features)
        records = self.log.read()
        feats_by_id = {
            r["event_id"]: r["features"]
            for r in records
            if r.get("event_type") == "tool-proposed" and r.get("event_id") and r.get("features")
        }
        for r in reversed(records):
            if r.get("event_type") != "user-responded" or r.get("harm_observation") is None:
                continue
            feats = feats_by_id.get(str(r.get("in_response_to")))
            if feats is not None and _harm_cell(feats) == cell:
                return int(r["harm_observation"]) == int(verdict)
        return False

    # ── the async sensor dispatch (in-process plugins) ──
    def dispatch(self, event: dict[str, Any]) -> None:
        typ = str(event.get("event_type") or "")
        event_id = str(event.get("event_id") or "")
        if typ == "tool-proposed":
            features = self.features_for(event)
            with self.lock:
                action = self.session.decide(features, features, event.get("profile"))
            self.log.append({"event_type": "tool-proposed", "event_id": event_id,
                             "features": features, "ts": round(time.time(), 3)})
            if action == "ask":
                self._pending_asks[event_id] = features
            self._emit_decision(
                event_id, action, event.get("proposed_call"),
                _rationale(features, _block_category(features)),
            )
            self._remember_features(event_id, features)
            self._shadow_decide(event_id, features, event.get("profile"))
        elif typ == "user-responded":
            original = str(event.get("in_response_to") or "")
            # Pop unconditionally so timeouts / other responses don't leak the entry;
            # only yes/no are labels the belief learns from.
            features = self._pending_asks.pop(original, None)
            response = str(event.get("response") or "")
            record = {"event_type": "user-responded", "in_response_to": original, "response": response}
            if features and response in ("yes", "no"):
                obs = 1 if response == "yes" else 0
                extra = self._plan_verdict(features, obs)
                record.update(extra)
                self.log.append(record)
                with self.lock:
                    self._condition_verdict(features, obs, extra)
            else:
                self.log.append(record)
        elif typ == "route-request":
            features = event.get("features") or {}
            with self.lock:
                choice = self.session.route(features, event.get("models"), event.get("profile"))
            if choice and choice.get("model"):
                sid = str(event.get("session_id") or "")
                if sid:
                    self._pending_routes[sid] = {"model": choice["model"], "features": features}
                self.log.append({"event_type": "route-decision", "in_response_to": event_id, "model": choice["model"]})
                self._emit(
                    {
                        "signal_type": "route",
                        "signal_id": _short_id("sig"),
                        "in_response_to": event_id,
                        "effector": "route",
                        "parameters": {"model": choice["model"], "provider": choice.get("provider"), "name": choice.get("name")},
                    }
                )
        elif typ == "tool-completed":
            sid = str(event.get("session_id") or "")
            outcome = event.get("outcome") or {}
            # Pop so each routing decision is credited exactly ONCE (else every later
            # tool-completed in the session re-applies the same outcome — evidence
            # over-counting — and entries accumulate unboundedly).
            pending = self._pending_routes.pop(sid, None)
            success = bool(outcome.get("success", True))
            if pending:
                with self.lock:
                    self.session.route_outcome(pending["model"], pending["features"], success)
                self.log.append({"event_type": "route-outcome", "model_id": pending["model"], "features": pending["features"], "success": success})
            # When the completion names a governance decision (in_response_to == a logged
            # tool-proposed event_id — the openclaw body correlates by the governance eventId,
            # not the tool-call id), ALSO record its measured outcome. Independent of the
            # routing credit above: one credits the routed MODEL, this links the DECISION to
            # what happened after it. Ignored when in_response_to is a bare tool-call id
            # (no matching proposal) so a pre-fix body logs nothing spurious.
            irt = str(event.get("in_response_to") or "")
            if irt and irt in self._governance_event_ids():
                dur = outcome.get("duration_ms")
                latency_s = dur / 1000.0 if isinstance(dur, (int, float)) else None
                record = _outcome_record(
                    irt, "openclaw",
                    completed=outcome.get("success"),
                    latency_s=latency_s,
                    error=outcome.get("error"),
                )
                self.log.append(record)
                self._shadow_outcome(record)
        else:
            # turn-cost / governance-latency / counterfactual-decision: telemetry — log only.
            self.log.append(dict(event))

    def report(self) -> dict[str, Any]:
        records = self.log.read()
        decisions: dict[str, int] = {}
        would_block = 0
        total_usd = 0.0
        outcome_records = 0
        completed = 0
        reverted = 0
        for r in records:
            et = r.get("event_type")
            if et == "decision":
                a = str(r.get("action"))
                decisions[a] = decisions.get(a, 0) + 1
            elif et == "counterfactual-decision":
                would_block += 1
            elif et == "turn-cost":
                usd = r.get("usd")
                if isinstance(usd, (int, float)):
                    total_usd += usd
            elif et == "outcome":
                outcome_records += 1
                spend = r.get("spend_usd")
                if isinstance(spend, (int, float)):
                    total_usd += spend
                if r.get("completed") is True:
                    completed += 1
                if r.get("reverted") is True:
                    reverted += 1
        out = {
            # Existing keys (unchanged — existing consumers/tests depend on them).
            "events": len(records),
            "decisions": decisions,
            # Aggregates the session-summary surface reads: measured observables only,
            # no fabricated savings estimate.
            "total_events": sum(decisions.values()),
            "prevented_calls": decisions.get("block", 0),
            "would_block_calls": would_block,
            "total_usd": total_usd,
            "outcome_records": outcome_records,
            "completed": completed,
            "reverted": reverted,
        }
        if self.shadow is not None:
            out["membrane_shadow"] = self.shadow.stats()
        return out

    # ── HTTP ──
    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # quiet; route through daemon.logline if needed
                pass

            def _json(self, code: int, obj: Any) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict[str, Any]:
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n) if n else b""
                return json.loads(raw) if raw else {}

            def do_GET(self):  # noqa: N802
                url = self.path or ""
                if url.startswith("/signals"):
                    return self._signals()
                if url.startswith("/report"):
                    return self._json(200, daemon.report())
                if url.startswith("/ready") or url == "/":
                    if daemon.ready.is_set():
                        return self._json(200, {"status": "ready"})
                    return self._json(503, {"status": "booting"})
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802
                url = self.path or ""
                # Booting: bound + serving, but the engine isn't ready yet. Answer a fast
                # 503 (fail-open) so an early tool call proceeds immediately instead of
                # waiting out the client's timeout — and a duplicate daemon that lost the
                # bind has already exited rather than booting a second engine.
                if not daemon.ready.is_set():
                    if url.startswith("/decide") or url.startswith("/sensor"):
                        return self._json(503, {"status": "booting", "action": "proceed"})
                    if url.startswith("/feedback"):
                        # feedback conditions the belief, which needs the engine — can't fail
                        # open into a no-op; tell the caller to retry once ready.
                        return self._json(503, {"ok": False, "status": "booting", "error": "daemon still booting"})
                if url.startswith("/decide"):
                    try:
                        payload = self._read_body()
                        return self._json(200, daemon.decide_sync(payload))
                    except Exception as err:  # fail-open
                        daemon.logline(f"credence-governor: /decide error (failing open): {err}")
                        return self._json(200, {"action": "proceed", "error": str(err)})
                if url.startswith("/sensor"):
                    try:
                        event = self._read_body()
                        daemon.dispatch(event)
                    except Exception as err:  # fail-open
                        daemon.logline(f"credence-governor: sensor error (failing open): {err}")
                    return self._json(200, {"ack": True})
                if url.startswith("/result"):
                    # Result-time outcome capture: append-only telemetry, no engine — so it
                    # runs even while booting (and is fail-open: a bad record must never
                    # surface as an error to the result hook, which swallows it regardless).
                    try:
                        payload = self._read_body()
                        return self._json(200, daemon.result_sync(payload))
                    except Exception as err:
                        daemon.logline(f"credence-governor: /result error (non-fatal): {err}")
                        return self._json(200, {"ok": False, "error": str(err)})
                if url.startswith("/feedback"):
                    try:
                        payload = self._read_body()
                        if "observation" not in payload:
                            return self._json(400, {"ok": False, "error": "observation (0|1) required"})
                        return self._json(200, daemon.feedback(payload.get("event_id"), int(payload["observation"])))
                    except Exception as err:
                        daemon.logline(f"credence-governor: /feedback error: {err}")
                        return self._json(400, {"ok": False, "error": str(err)})
                self.send_response(404)
                self.end_headers()

            def _signals(self):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "keep-alive")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                with daemon._subs_lock:
                    daemon._subscribers.add(q)
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        # Heartbeat on idle so a disconnect surfaces (broken pipe on
                        # flush) instead of the thread parking on get() forever while
                        # _emit keeps filling a dead queue.
                        try:
                            frame = q.get(timeout=15)
                        except queue.Empty:
                            frame = ": ping\n\n"
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                    pass
                finally:
                    with daemon._subs_lock:
                        daemon._subscribers.discard(q)

        return Handler

    def bind(self, host: str, port: int) -> ThreadingHTTPServer:
        """Construct + bind the HTTP server (claims the port) WITHOUT booting the engine.
        Binding before the ~18s engine boot is what makes a duplicate daemon fail fast on
        EADDRINUSE instead of booting a whole second engine. Raises OSError if taken."""
        httpd = ThreadingHTTPServer((host, port), self._handler_class())
        httpd.daemon_threads = True
        return httpd

    def start(self, httpd: ThreadingHTTPServer) -> None:
        """Begin accepting requests. Safe to call before the engine is booted — the
        ready-gate answers 503 (fail-open) on /ready, /decide and /sensor until ready."""
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def serve_forever(self, host: str, port: int) -> ThreadingHTTPServer:
        httpd = self.bind(host, port)
        self.start(httpd)
        return httpd
