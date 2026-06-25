"""credence-governor-core — harness- and domain-neutral Bayesian tool-call
governance. A pure wire consumer of the Credence engine (credence-skin): it
extracts features from a neutral AgentToolEvent/Session, and drives proceed/block/
ask decisions over the protocol-versioned skin wire. Carries no probabilistic code.
"""

from __future__ import annotations

import os
import signal
import threading

from .daemon import Daemon, data_dir
from .features import extract_features, extractors
from .log import ObservationLog
from .safety import extract_safety
from .schema import AgentToolEvent, Message, Session, event_and_session_from_payload
from .session import BrainSession

__all__ = [
    "AgentToolEvent",
    "Message",
    "Session",
    "event_and_session_from_payload",
    "extract_features",
    "extractors",
    "extract_safety",
    "BrainSession",
    "ObservationLog",
    "Daemon",
    "data_dir",
    "build_skin_client",
    "run",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def build_skin_client():
    """The engine: a pinned credence-skin image in prod, or a local julia server.jl in dev."""
    from credence_skin_client import SkinClient

    cmd = os.environ.get("CREDENCE_SKIN_COMMAND")  # e.g. "docker run --rm -i ghcr.io/gfrmin/credence-skin@sha256:…"
    if cmd:
        return SkinClient(command=cmd.split())
    engine = os.environ.get("CREDENCE_ENGINE_DIR")  # dev: an engine checkout
    if engine:
        return SkinClient(
            server_path=os.path.join(engine, "apps", "skin", "server.jl"),
            project=engine,
        )
    raise RuntimeError(
        "set CREDENCE_SKIN_COMMAND (docker run -i credence-skin@digest) or "
        "CREDENCE_ENGINE_DIR (dev engine checkout)"
    )


def run() -> None:
    """Boot the beliefs and serve the HTTP wire until SIGINT/SIGTERM."""
    host = os.environ.get("CREDENCE_GOVERNOR_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CREDENCE_GOVERNOR_PORT", str(DEFAULT_PORT)))
    brain_dir = os.environ.get("CREDENCE_GOVERNOR_BRAIN_DIR", os.path.join(data_dir(), "brain"))
    log_path = os.environ.get(
        "CREDENCE_GOVERNOR_LOG",
        os.path.join(os.path.expanduser("~"), ".credence-governor", "observations.jsonl"),
    )

    log = ObservationLog(log_path)
    skin = build_skin_client()
    engine_lock = threading.Lock()
    session = BrainSession(skin, brain_dir, log)
    session.boot()
    daemon = Daemon(session, log, engine_lock, logline=lambda m: print(m, flush=True))
    httpd = daemon.serve_forever(host, port)
    print(
        f"credence-governor daemon listening on http://{host}:{port} "
        f"(brain={brain_dir}, log={log_path})",
        flush=True,
    )

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        stop.wait()
    finally:
        httpd.shutdown()
        skin.shutdown()


if __name__ == "__main__":
    run()
