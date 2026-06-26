"""credence-governor-core — harness- and domain-neutral Bayesian tool-call
governance. A pure wire consumer of the Credence engine (credence-skin): it
extracts features from a neutral AgentToolEvent/Session, and drives proceed/block/
ask decisions over the protocol-versioned skin wire. Carries no probabilistic code.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import threading
from typing import Callable

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

# The published engine image. Single source of truth: used by the zero-config
# container path AND quoted in the no-engine error so the hint is copy-pasteable.
DEFAULT_SKIN_IMAGE = "ghcr.io/gfrmin/credence-skin:latest"


def _stdout(msg: str) -> None:
    print(msg, flush=True)


def _container_runtime() -> str | None:
    """First available container runtime on PATH — docker preferred, podman next.

    CREDENCE_CONTAINER_RUNTIME forces the choice (for hosts that have both)."""
    forced = os.environ.get("CREDENCE_CONTAINER_RUNTIME")
    if forced:
        return forced if shutil.which(forced) else None
    for rt in ("docker", "podman"):
        if shutil.which(rt):
            return rt
    return None


def _runtime_label(runtime: str) -> str:
    """Honest provenance only: `docker` is often a podman shim (podman-docker).
    The argv is identical either way — podman is docker-CLI-compatible — so this
    affects the printed line, never control flow."""
    if runtime != "docker":
        return runtime
    try:
        out = subprocess.run(
            [runtime, "--version"], capture_output=True, text=True, timeout=5
        )
        if "podman" in (out.stdout + out.stderr).lower():
            return "docker (podman shim)"
    except (OSError, subprocess.SubprocessError):
        pass
    return "docker"


def _ensure_image(runtime: str, image: str, log: Callable[[str], None]) -> None:
    """Pull the engine image with VISIBLE progress if it isn't local yet.

    Otherwise `<runtime> run` pulls it silently and — because the skin client pipes
    the child's stderr — docker's own progress is swallowed and the daemon looks hung
    for the whole download (and can trip the client's ready-timeout). Pulling here with
    stdio inherited makes it visible and keeps the pull out of the ready-wait budget."""
    present = (
        subprocess.run(
            [runtime, "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    if present:
        return
    log(f"credence-governor: pulling engine image {image} (first run may take a minute)…")
    rc = subprocess.run([runtime, "pull", image]).returncode  # stdio inherited
    if rc != 0:
        log(
            f"credence-governor: warning — `{runtime} pull {image}` exited {rc}; "
            "the engine may fail to start"
        )


def build_skin_client(log: Callable[[str], None] = _stdout):
    """Resolve the Credence engine to drive over the skin wire, in priority order:

      1. CREDENCE_SKIN_COMMAND — explicit launch argv (a digest-pinned image, extra
         flags, a remote runtime). Used verbatim.
      2. CREDENCE_ENGINE_DIR   — a dev engine checkout (runs apps/skin/server.jl).
      3. zero-config           — docker/podman on PATH ⇒ run the published image
         (CREDENCE_SKIN_IMAGE overrides the tag/image).

    Prints the chosen source; raises an actionable error naming all three if none resolve."""
    from credence_skin_client import SkinClient

    # 1. explicit command — verbatim (shlex so quoted args survive).
    cmd = os.environ.get("CREDENCE_SKIN_COMMAND")
    if cmd:
        argv = shlex.split(cmd)
        log(f"credence-governor: engine = CREDENCE_SKIN_COMMAND ({' '.join(argv)})")
        return SkinClient(command=argv)

    # 2. dev checkout — local julia server.jl.
    engine = os.environ.get("CREDENCE_ENGINE_DIR")
    if engine:
        log(f"credence-governor: engine = CREDENCE_ENGINE_DIR dev checkout ({engine})")
        return SkinClient(
            server_path=os.path.join(engine, "apps", "skin", "server.jl"),
            project=engine,
        )

    # 3. zero-config — the published image via docker/podman.
    runtime = _container_runtime()
    if runtime:
        image = os.environ.get("CREDENCE_SKIN_IMAGE", DEFAULT_SKIN_IMAGE)
        log(f"credence-governor: engine = {_runtime_label(runtime)} image {image}")
        _ensure_image(runtime, image, log)
        return SkinClient(command=[runtime, "run", "--rm", "-i", image])

    # 4. nothing resolved — name all three remedies.
    raise RuntimeError(
        "no Credence engine found. Set one of:\n"
        f"  - install docker or podman — the daemon then auto-runs {DEFAULT_SKIN_IMAGE}\n"
        "      (override the image with CREDENCE_SKIN_IMAGE)\n"
        "  - CREDENCE_SKIN_COMMAND — an explicit launch argv, e.g.\n"
        f"      docker run --rm -i {DEFAULT_SKIN_IMAGE}\n"
        "  - CREDENCE_ENGINE_DIR — a dev engine checkout (runs apps/skin/server.jl)"
    )


def _print_banner(
    host: str, port: int, brain_dir: str, log_path: str, log: Callable[[str], None]
) -> None:
    bar = "=" * 64
    log(bar)
    log("  credence-governor READY -- now governing every tool call")
    log(f"  listening   http://{host}:{port}   (GET /ready - POST /decide - GET /report)")
    log("  Adapters (Claude Code hook - OpenClaw plugin) ask THIS daemon")
    log("  for every tool call. Daemon down => adapters FAIL OPEN: tools")
    log("  run ungoverned, never blocked. Keep it up to add governance.")
    log(f"  brain = {brain_dir}")
    log(f"  log   = {log_path}")
    log(bar)


def run() -> None:
    """Boot the beliefs and serve the HTTP wire until SIGINT/SIGTERM."""
    host = os.environ.get("CREDENCE_GOVERNOR_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CREDENCE_GOVERNOR_PORT", str(DEFAULT_PORT)))
    brain_dir = os.environ.get("CREDENCE_GOVERNOR_BRAIN_DIR", os.path.join(data_dir(), "brain"))
    log_path = os.environ.get(
        "CREDENCE_GOVERNOR_LOG",
        os.path.join(os.path.expanduser("~"), ".credence-governor", "observations.jsonl"),
    )

    _stdout("credence-governor: starting — resolving engine…")
    log = ObservationLog(log_path)
    skin = build_skin_client()  # prints engine provenance + any pull progress
    engine_lock = threading.Lock()
    session = BrainSession(skin, brain_dir, log)
    daemon = Daemon(session, log, engine_lock, logline=lambda m: print(m, flush=True))

    # Bind + serve BEFORE the ~18s engine boot. A duplicate daemon (e.g. a second
    # autostart) then fails fast here on EADDRINUSE instead of booting a whole second
    # engine and only crashing afterwards. Until daemon.ready is set, the ready-gate
    # answers a fast 503 (fail-open) so early tool calls proceed without waiting.
    try:
        httpd = daemon.bind(host, port)
    except OSError as err:
        skin.shutdown()
        raise SystemExit(
            f"credence-governor: {host}:{port} is already in use — a daemon is probably "
            "already running there (check GET /ready). Not starting a second one."
        ) from err

    daemon.start(httpd)
    try:
        _stdout(
            f"credence-governor: bound http://{host}:{port} — booting engine & warming "
            "beliefs… ~10-20s (first run also pulls the image). Tool calls FAIL OPEN "
            "(proceed ungoverned) until ready."
        )
        session.boot()
        daemon.ready.set()  # engine up → answer real decisions
        _print_banner(host, port, brain_dir, log_path, _stdout)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        stop.wait()
    finally:
        httpd.shutdown()
        skin.shutdown()


if __name__ == "__main__":
    run()
