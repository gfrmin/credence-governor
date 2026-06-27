# credence-governor-core

The harness- and domain-neutral Bayesian tool-call governance core for
[credence-governor](https://github.com/gfrmin/credence-governor) — a **pure wire
consumer** of the Credence engine (`credence-skin`). It carries **no probabilistic
code**: all inference runs server-side in the engine, reached over the
protocol-versioned JSON-RPC skin wire; this package only extracts features from a
neutral event and drives `proceed` / `block` / `ask` decisions.

## What's in it

- **`schema.py`** — the harness-neutral contract: `AgentToolEvent`, `Session`,
  `Message`. Every adapter translates its native events into these shapes.
- **`features/` + `safety.py`** — the single source of truth for feature & taint
  extraction (waste loops, repetition, taint-flow, exfil chains). Adapters carry
  none of this; they send a `Session` and the daemon extracts.
- **`session.py`** (`BrainSession`) — boots the warm beliefs and drives the engine's
  `structure_bma` / `structure_observe` / `structure_decide` / `routing_*` verbs.
- **`daemon.py`** — the HTTP surface: `POST /decide` (synchronous, for subprocess-hook
  adapters), `POST /sensor` + `GET /signals` (SSE, for in-process plugins), `/report`,
  `/ready`. stdlib `http.server`; one lock serialises engine calls.
- **`data/`** — "coding-ness" as data: the `bdsl/` feature schema + utility, the
  `brain/*.counts.json` warm beliefs, and `profiles/`. Swappable.

## Install & run

**Zero-config** — with docker or podman on PATH, the daemon auto-runs the published
engine image (`ghcr.io/gfrmin/credence-skin:latest`); no env vars needed:

```bash
pip install credence-governor-core   # pulls the engine's wire client (credence-skin-client)
credence-governor-daemon             # zero-config: auto-runs the engine via docker/podman
```

**With [uv](https://docs.astral.sh/uv/)** — no separate install step. The package is
`credence-governor-core` but the console script is `credence-governor-daemon`, so the
`--from` is **required** (`uvx` otherwise looks for a PyPI package matching the command name):

```bash
# one-off / ephemeral — re-resolves each run (cached after the first):
uvx --from credence-governor-core credence-governor-daemon

# persistent — installs `credence-governor-daemon` onto PATH (~/.local/bin):
uv tool install credence-governor-core
credence-governor-daemon
```

Prefer `uv tool install` for a long-lived service, and **required** if you use an adapter's
opt-in **autostart** — it spawns the bare `credence-governor-daemon`, which must be on PATH
(an ephemeral `uvx` install is not). `uvx` is ideal for a quick "spin it up to test". Either
way uv supplies only the Python host; the engine still comes from docker/podman (or the
overrides below).

Overrides (resolution order: `CREDENCE_SKIN_COMMAND` → `CREDENCE_ENGINE_DIR` → zero-config):

```bash
# prod: pin the engine image by digest (reproducible) — highest precedence
CREDENCE_SKIN_COMMAND="docker run --rm -i ghcr.io/gfrmin/credence-skin@sha256:<digest>" \
  credence-governor-daemon
# dev engine: a local checkout of the Credence engine
CREDENCE_ENGINE_DIR=/path/to/credence credence-governor-daemon
```

The daemon listens on `http://127.0.0.1:8787` by default
(`CREDENCE_GOVERNOR_HOST` / `CREDENCE_GOVERNOR_PORT`). **Every adapter is a fail-open
silent no-op until this daemon answers on `:8787`** — verify with
`curl -s localhost:8787/ready`.

`POST /decide` `{tool_name, input, session:{cwd, project_root, messages}}` →
`{action, features, event_id}`.

### Raw-event capture (opt-in)

The observation log stores only the *extracted features* of each decision, so when
the extractor gains a feature, past traffic cannot be re-derived. Set
`CREDENCE_GOVERNOR_CAPTURE=1` (or a path) to additionally capture the raw
`(tool_name, input, session)` of each governed call to `~/.credence-governor/raw_events.jsonl`
— a **re-extractable** corpus a later feature-engineering pass folds in as benign
negatives (`training.capture_corpus.load_capture`). **Off by default** (raw sessions
carry file contents + commands); string fields are truncated to
`CREDENCE_GOVERNOR_CAPTURE_MAXLEN` (default 8192). Non-causal: capture never feeds a
belief or a decision.

## Tests

```bash
python -m pytest tests -q   # parity tests; no engine needed (pure extractor/manifest code)
```

## License

AGPL-3.0-or-later.
