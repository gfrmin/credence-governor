"""shadow.py — the membrane SHADOW subsystem (governance-roadmap Phase 2).

A `MembraneShadow` runs one or more `MembraneSession`s (one govhost
subprocess per declared utility form) BESIDE the primary Julia engine:
every live decide/verdict/outcome is mirrored to the shadow sessions,
every shadow decision is appended to the observation log as a
`membrane-shadow` record (replay-inert — all `log.replay_*` filter by
event_type), and NOTHING the shadow does can reach the primary response
path. That isolation is structural, not best-effort:

* the submit_* surface is enqueue-only and never raises — a full queue
  drops (counted), an exception is swallowed (counted);
* one dedicated worker thread exclusively owns the sessions; the
  primary `engine_lock` is never touched, so shadow latency (an ~8 ms
  engine tick, or a minutes-long boot replay) never adds to a decision;
* a session failure marks that form dead and respawns it (bounded:
  `max_respawns` per daemon lifetime, `respawn_backoff_s` between
  attempts), then permanently dead until the daemon restarts. The
  queue keeps draining either way.

Boot replay vs live feed: `start()` snapshots the observation log
SYNCHRONOUSLY (call it before the HTTP server serves); the worker boots
each session against that frozen snapshot, and everything after arrives
only via submit_* — so a record can never be fed twice as both replay
and live evidence. Events that arrive while a dead form awaits respawn
are lost for that form (telemetry, documented).

Selection: `CREDENCE_MEMBRANE_COMMAND` (absence = shadow disabled =
zero behavior change); `CREDENCE_MEMBRANE_UTILITY` = comma-separated
utility forms (default `latent@1`; the field deploy runs
`table@1,latent@1` — the dual shadow: table@1 is the non-degenerate
challenger policy the outcome bench scores, latent@1 is the wire-v2
field reading; docs/membrane-shadow.md carries the register).

The queue bound, respawn cap and backoff are adapter TRANSPORT knobs
(the HOSTS_PLAN 2.5 class) — they shape delivery, never a decision.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Callable

from .log import ObservationLog
from .membrane import MEMBRANE_ENV, UTILITY_FORMS, MembraneSession, build_membrane_session

UTILITY_FORM_ENV = "CREDENCE_MEMBRANE_UTILITY"

# the observability scalars a decision reply may carry (membrane-wire.md
# 6.4) — LOGGED for the record, never branched on (HOSTS_PLAN 8.12(b)).
_READOUT_KEYS = ("p1", "entropy_bits", "residual_mean", "sensitivity")


class _SnapshotLog(ObservationLog):
    """A frozen read-only view of the records captured at shadow start —
    the boot-replay source for shadow sessions. Live appends after the
    snapshot can never double-feed a booting session; shadow sessions
    never write."""

    def __init__(self, records: list[dict[str, Any]]):
        super().__init__(log_path="")
        self._records = records
        self.n_records = len(records)

    def read(self) -> list[dict[str, Any]]:
        return list(self._records)

    def append(self, record: dict[str, Any]) -> None:
        raise RuntimeError("shadow snapshot log is read-only")


class _FormState:
    """One utility form's session + lifecycle counters (worker-owned)."""

    def __init__(self, form: str,
                 factory: Callable[[ObservationLog], MembraneSession]):
        self.form = form
        self.factory = factory
        self.session: MembraneSession | None = None
        self.alive = False
        self.respawns = 0
        self.next_attempt_at = 0.0
        self.decides = 0
        self.errors = 0
        self.boot_s: float | None = None
        # boot-replay coverage marker: how many log records this session's
        # boot snapshot held — lets a reading flag respawn evidence gaps.
        self.snapshot_records: int | None = None


class MembraneShadow:
    def __init__(
        self,
        session_factories: list[tuple[str, Callable[[ObservationLog], MembraneSession]]],
        log: ObservationLog,
        logline: Callable[[str], None] = print,
        queue_max: int = 1024,
        max_respawns: int = 3,
        respawn_backoff_s: float = 60.0,
    ):
        self._forms = [_FormState(form, factory) for form, factory in session_factories]
        self._log = log
        self._logline = logline
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self._max_respawns = max_respawns
        self._backoff_s = respawn_backoff_s
        self._drops = 0
        self._closed = threading.Event()
        self._snapshot: _SnapshotLog | None = None
        self._thread: threading.Thread | None = None

    # ── the never-raise submit surface (handler threads call these) ──
    def _submit(self, item: tuple) -> None:
        try:
            self._q.put_nowait(item)
        except Exception:  # noqa: BLE001 — queue.Full or anything else: drop, never raise
            self._drops += 1

    def submit_decide(self, event_id: str, features: dict[str, str],
                      profile: dict[str, float] | None = None) -> None:
        self._submit(("decide", event_id, dict(features), profile))

    def submit_verdict(self, features: dict[str, str], observation: int) -> None:
        self._submit(("verdict", dict(features), int(observation)))

    def submit_outcome(self, event_id: str, features: dict[str, str],
                       good: int) -> None:
        self._submit(("outcome", event_id, dict(features), int(good)))

    # ── lifecycle ──
    def start(self) -> None:
        """Snapshot the log SYNCHRONOUSLY (call before the HTTP server
        serves), then start the worker that boots and drives the shadow
        sessions."""
        self._snapshot = _SnapshotLog(self._log.read())
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="membrane-shadow")
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                # the worker is parked in a blocking wire read (a wedged
                # driver): force-kill the children so the read unblocks
                # (EOF) and the worker exits — never leak a govhost child
                # past daemon shutdown. Popen.kill from another thread is
                # safe; the worker's own error path tolerates the EOF.
                for st in self._forms:
                    session = st.session
                    if session is not None:
                        try:
                            session.client.shutdown()
                        except Exception:  # noqa: BLE001
                            pass
                self._thread.join(timeout=5)

    def stats(self) -> dict[str, Any]:
        return {
            "queue": self._q.qsize(),
            "drops": self._drops,
            "forms": {
                st.form: {
                    "alive": st.alive,
                    "respawns": st.respawns,
                    "decides": st.decides,
                    "errors": st.errors,
                    "boot_s": st.boot_s,
                    "snapshot_records": st.snapshot_records,
                }
                for st in self._forms
            },
        }

    # ── worker internals (the thread below exclusively owns sessions) ──
    def _boot(self, st: _FormState) -> None:
        assert self._snapshot is not None
        t0 = time.monotonic()
        try:
            st.snapshot_records = self._snapshot.n_records
            st.session = st.factory(self._snapshot)
            st.session.boot()
            st.boot_s = round(time.monotonic() - t0, 3)
            st.alive = True
            self._logline(
                f"credence-governor: membrane shadow [{st.form}] booted "
                f"in {st.boot_s}s")
        except Exception as err:  # noqa: BLE001 — a shadow boot failure is telemetry
            st.errors += 1
            self._mark_dead(st, f"boot failed: {err}")

    def _mark_dead(self, st: _FormState, why: str) -> None:
        st.alive = False
        if st.session is not None:
            try:
                st.session.client.shutdown()
            except Exception:  # noqa: BLE001
                pass
            st.session = None
        if st.respawns < self._max_respawns:
            st.next_attempt_at = time.monotonic() + self._backoff_s
            self._logline(
                f"credence-governor: membrane shadow [{st.form}] dead ({why}); "
                f"respawn {st.respawns + 1}/{self._max_respawns} in {self._backoff_s}s")
        else:
            self._logline(
                f"credence-governor: membrane shadow [{st.form}] dead ({why}); "
                "respawn budget exhausted — dead until daemon restart")

    def _maybe_respawn(self, st: _FormState) -> None:
        if st.alive or st.respawns >= self._max_respawns:
            return
        if time.monotonic() < st.next_attempt_at:
            return
        st.respawns += 1
        # refresh the boot snapshot: a respawned session must not reboot
        # from the day-zero state and silently miss every verdict/outcome
        # that arrived since (review finding, PR #26). Outcomes re-dedup
        # via the fresh session's boot-fed seen-set; the residual risk is
        # a verdict enqueued-but-undispatched at this instant being fed
        # twice (already in the new snapshot AND still in the queue) —
        # rare, telemetry-only, documented in docs/membrane-shadow.md.
        self._snapshot = _SnapshotLog(self._log.read())
        self._boot(st)

    def _dispatch(self, st: _FormState, item: tuple) -> None:
        session = st.session
        if session is None:
            return
        kind = item[0]
        if kind == "decide":
            _kind, event_id, features, profile = item
            t0 = time.monotonic()
            action = session.decide(features, features, profile)
            latency_ms = round((time.monotonic() - t0) * 1000, 3)
            st.decides += 1
            readouts = {
                k: v for k, v in session.last_readouts.items()
                if k in _READOUT_KEYS
            }
            self._log.append({
                "event_type": "membrane-shadow",
                "in_response_to": event_id,
                "utility_form": st.form,
                "action": action,
                "latency_ms": latency_ms,
                "readouts": readouts,
            })
        elif kind == "verdict":
            _kind, features, obs = item
            session.observe(features, obs)
        elif kind == "outcome":
            _kind, event_id, features, good = item
            session.observe_outcome(event_id, features, good)

    def _run(self) -> None:
        for st in self._forms:
            if self._closed.is_set():
                break
            self._boot(st)
        while not self._closed.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                for st in self._forms:
                    self._maybe_respawn(st)
                continue
            for st in self._forms:
                self._maybe_respawn(st)
                if not st.alive:
                    continue
                try:
                    self._dispatch(st, item)
                except Exception as err:  # noqa: BLE001 — isolate: mark dead, keep draining
                    st.errors += 1
                    self._mark_dead(st, str(err))
        for st in self._forms:
            if st.session is not None:
                try:
                    st.session.client.shutdown()
                except Exception:  # noqa: BLE001
                    pass
                st.session = None
                st.alive = False


def build_shadow_from_env(
    brain_dir: str, log: ObservationLog,
    logline: Callable[[str], None] = print,
) -> MembraneShadow | None:
    """The shadow, iff CREDENCE_MEMBRANE_COMMAND is set (absence =
    disabled = zero behavior change). CREDENCE_MEMBRANE_UTILITY selects
    the utility forms, comma-separated (default latent@1); an unknown
    form fails loudly HERE, at construction before serving, not
    silently in the worker."""
    if not os.environ.get(MEMBRANE_ENV):
        return None
    raw = os.environ.get(UTILITY_FORM_ENV, "latent@1")
    forms: list[str] = []
    for f in (part.strip() for part in raw.split(",")):
        if not f or f in forms:
            continue
        if f not in UTILITY_FORMS:
            raise ValueError(
                f"{UTILITY_FORM_ENV}={raw!r}: unknown utility form {f!r} "
                f"(known: {', '.join(UTILITY_FORMS)})")
        forms.append(f)
    if not forms:
        return None

    def factory_for(form: str) -> Callable[[ObservationLog], MembraneSession]:
        def make(snapshot: ObservationLog) -> MembraneSession:
            return build_membrane_session(
                brain_dir, snapshot, logline, utility_form=form)
        return make

    return MembraneShadow(
        [(form, factory_for(form)) for form in forms], log, logline=logline)
