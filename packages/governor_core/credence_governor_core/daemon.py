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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable

from .features import extract_features
from .log import ObservationLog
from .safety import extract_safety
from .schema import event_and_session_from_payload
from .session import BrainSession


def data_dir() -> str:
    """Absolute path to the bundled governance data (bdsl/, brain/, profiles/)."""
    return str(resources.files("credence_governor_core") / "data")


def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _ask_text(proposed: Any) -> str:
    tool = str((proposed or {}).get("tool_name") or (proposed or {}).get("tool") or "(unknown)")
    inp = (proposed or {}).get("input")
    s = "(none)" if inp is None else json.dumps(inp)
    if len(s) > 80:
        s = s[:80] + "…"
    return f"Allow `{tool}` to run with input `{s}`?"


def _action_signal(action: str, proposed: Any) -> dict[str, Any]:
    if action == "ask":
        return {"effector": "ask", "parameters": {"text": _ask_text(proposed)}}
    if action == "block":
        return {"effector": "block", "parameters": {"reason": "Refused based on prior approval observations."}}
    return {"effector": "proceed", "parameters": {}}


class Daemon:
    def __init__(
        self,
        session: BrainSession,
        log: ObservationLog,
        engine_lock: threading.Lock,
        logline: Callable[[str], None] = lambda m: None,
    ):
        self.session = session
        self.log = log
        self.lock = engine_lock
        self.logline = logline
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
        return {**extract_features(event, session), **extract_safety(event, session)}

    # ── SSE ──
    def _emit(self, signal: dict[str, Any]) -> None:
        frame = f"data: {json.dumps(signal)}\n\n"
        with self._subs_lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(frame)

    def _emit_decision(self, in_response_to: str, action: str, proposed: Any) -> None:
        self.log.append({"event_type": "decision", "in_response_to": in_response_to, "action": action})
        eff = _action_signal(action, proposed)
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
        self.log.append({"event_type": "tool-proposed", "event_id": event_id, "features": features})
        self.log.append({"event_type": "decision", "in_response_to": event_id, "action": action})
        return {"action": action, "features": features, "event_id": event_id}

    # ── the async sensor dispatch (in-process plugins) ──
    def dispatch(self, event: dict[str, Any]) -> None:
        typ = str(event.get("event_type") or "")
        event_id = str(event.get("event_id") or "")
        if typ == "tool-proposed":
            features = self.features_for(event)
            with self.lock:
                action = self.session.decide(features, features, event.get("profile"))
            self.log.append({"event_type": "tool-proposed", "event_id": event_id, "features": features})
            if action == "ask":
                self._pending_asks[event_id] = features
            self._emit_decision(event_id, action, event.get("proposed_call"))
        elif typ == "user-responded":
            original = str(event.get("in_response_to") or "")
            # Pop unconditionally so timeouts / other responses don't leak the entry;
            # only yes/no are labels the belief learns from.
            features = self._pending_asks.pop(original, None)
            response = str(event.get("response") or "")
            self.log.append({"event_type": "user-responded", "in_response_to": original, "response": response})
            if features and response in ("yes", "no"):
                with self.lock:
                    self.session.observe(features, 1 if response == "yes" else 0)
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
            # Pop so each routing decision is credited exactly ONCE (else every later
            # tool-completed in the session re-applies the same outcome — evidence
            # over-counting — and entries accumulate unboundedly).
            pending = self._pending_routes.pop(sid, None)
            success = bool((event.get("outcome") or {}).get("success", True))
            if pending:
                with self.lock:
                    self.session.route_outcome(pending["model"], pending["features"], success)
                self.log.append({"event_type": "route-outcome", "model_id": pending["model"], "features": pending["features"], "success": success})
        else:
            # turn-cost / governance-latency / counterfactual-decision: telemetry — log only.
            self.log.append(dict(event))

    def report(self) -> dict[str, Any]:
        records = self.log.read()
        decisions: dict[str, int] = {}
        for r in records:
            if r.get("event_type") == "decision":
                a = str(r.get("action"))
                decisions[a] = decisions.get(a, 0) + 1
        return {"events": len(records), "decisions": decisions}

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
                if not daemon.ready.is_set() and (
                    url.startswith("/decide") or url.startswith("/sensor")
                ):
                    return self._json(503, {"status": "booting", "action": "proceed"})
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
