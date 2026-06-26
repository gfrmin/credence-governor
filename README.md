# credence-governor

Bayesian tool-call governance for coding agents — one brain, thin per-harness
adapters. The agent's tool calls are gated by a Bayesian decision
(`proceed` / `block` / `ask`) computed by the **Credence** decision engine.

> **The daemon is required.** Both adapters fail open: with no `credence-governor`
> daemon on `:8787`, every tool call proceeds ungoverned — no governance, no error.
> Start it with **`credence-governor-daemon`** (zero-config if docker/podman is
> installed); verify with `curl -s localhost:8787/ready`.

## Architecture — a pure wire consumer

credence-governor carries **zero probabilistic code**. All inference and decisions
run inside the versioned **`credence-skin`** engine image; the daemon drives it
over the protocol-versioned JSON-RPC **skin wire** (stdio), holding only opaque
server-side handles. An app declares its domain as **data** (the `bdsl/` feature
schema + utility, the `brain/*.counts.json` warm beliefs) and calls the engine's
verbs; it never holds a probability or does arithmetic on one.

```
adapters (thin, in the harness's forced language)
  openclaw/      TS shim  (in-process plugin) ──┐
  claude-code/   Python hook (subprocess)     ──┤  native events → AgentToolEvent JSON
                                                ▼ HTTP (/decide, /sensor, /signals)
  packages/governor_core/  (Python, harness- & domain-neutral)
    daemon  ·  feature & taint extractors  ·  BrainSession  ── JSON-RPC/stdio ─▶ credence-skin
    coding-ness = DATA: data/{bdsl,brain,profiles}                               (the Julia engine)
```

The one abstraction seam is the normalized **`AgentToolEvent` + `Session`**: an
adapter's only job is `native events → that schema` (+ render the decision).
Feature/taint extraction is **server-side** (single-sourced in the core), so every
adapter stays thin. The policy *is* credence — one EU-max reasoner.

| Package | Role |
|---------|------|
| `packages/governor_core/` | Python core — daemon, neutral schema, extractors, BrainSession, the `bdsl`/`brain`/`profiles` data. Depends on the engine's `credence-skin-client`. |
| `adapters/openclaw/` | the OpenClaw plugin body (`@gfrmin/credence-openclaw`) — a thin TS shim forced by OpenClaw's Node runtime. |
| `adapters/claude-code/` | the Claude Code subprocess-hook adapter (Python). |

## Install

> All packages are published: the Python core/adapter on **PyPI**
> (`credence-governor-core`, `credence-governor-claude-code`) and the OpenClaw plugin on
> **npm + ClawHub** (`@gfrmin/credence-openclaw`). Requires Python ≥ 3.11; the OpenClaw
> adapter also needs Node ≥ 20.

### Step 1 — the daemon (required for every agent)

Both adapters talk to one local daemon. Install it and run it — **zero-config**: with
docker or podman on PATH it auto-runs the published engine image
(`ghcr.io/gfrmin/credence-skin:latest`), no env vars needed:

```bash
pip install credence-governor-core      # pulls credence-skin-client
credence-governor-daemon                # zero-config: auto-runs the engine via docker/podman
```

Using **[uv](https://docs.astral.sh/uv/)**? `uvx --from credence-governor-core
credence-governor-daemon` for a one-off run, or `uv tool install credence-governor-core` to
put `credence-governor-daemon` on PATH (the form an adapter's autostart needs). The `--from`
is required — the package (`credence-governor-core`) and script (`credence-governor-daemon`)
names differ.

Overrides, if you need them — pin a digest in prod, or use a dev engine checkout:

```bash
# prod — pin the engine image by digest (reproducible):
CREDENCE_SKIN_COMMAND="docker run --rm -i ghcr.io/gfrmin/credence-skin@sha256:<digest>" \
  credence-governor-daemon
# dev — a local engine checkout instead:
CREDENCE_ENGINE_DIR=~/git/credence credence-governor-daemon
```

It listens on `http://127.0.0.1:8787` (override with `CREDENCE_GOVERNOR_HOST` /
`CREDENCE_GOVERNOR_PORT`). Verify: `curl -s localhost:8787/ready`. **Until `/ready`
returns `{"status":"ready"}`, both adapters are a silent fail-open no-op.**
`POST /decide` `{tool_name, input, session:{cwd,project_root,messages}}` →
`{action: "proceed"|"block"|"ask"}`; also `GET /report` and the
`POST /sensor` + `GET /signals` (SSE) pair for in-process plugins.

**Keep it running (systemd user service).** So the daemon autostarts at login,
restarts on crash, and outlives any terminal, install the shipped unit
([`packages/governor_core/deploy/credence-governor.service`](packages/governor_core/deploy/credence-governor.service)):

```bash
uv tool install credence-governor-core          # binary on PATH at ~/.local/bin
mkdir -p ~/.config/systemd/user
cp packages/governor_core/deploy/credence-governor.service ~/.config/systemd/user/
loginctl enable-linger "$USER"                   # survive logout / reboot
systemctl --user enable --now credence-governor.service
```

Manage it with `systemctl --user {status,restart,stop} credence-governor` and
`journalctl --user -u credence-governor -f`. After `uv tool upgrade
credence-governor-core`, run `systemctl --user restart credence-governor` to pick
up the new version.

### Step 2a — govern **Claude Code** (PreToolUse hook)

Install it as a **plugin** — the hook is pure stdlib, so there's no `pip install`:

```
/plugin marketplace add gfrmin/credence-governor
/plugin install credence-governor-claude-code@credence-governor
```

Or skip the commands entirely: declare `extraKnownMarketplaces` + `enabledPlugins` in
`~/.claude/settings.json` and it auto-registers and auto-enables at next start — see
[`adapters/claude-code`](adapters/claude-code).

(Prefer pip? `pip install credence-governor-claude-code && credence-governor-cc-install`
registers the same hook in `~/.claude/settings.json`.)

With the daemon up, tool calls are now gated: `block` → deny, `ask` → prompt;
`proceed` defers to Claude Code's own rules — the governor only adds friction, never
removes it. Fail-open: if the daemon is down or slow, tools run normally. Both install
methods and the env table are in [`adapters/claude-code`](adapters/claude-code).

### Step 2b — govern **OpenClaw** (in-process plugin)

```bash
openclaw plugins install @gfrmin/credence-openclaw   # from npm/ClawHub
openclaw plugins enable credence-openclaw
# restart the gateway; confirm with: openclaw plugins list
```

(Developing against a checkout instead? `cd adapters/openclaw && npm install && npm run
build && openclaw plugins install -l .`)

As with Claude Code, this needs the Step-1 daemon: with nothing on `:8787`, routing and
governance silently no-op (fail-open). The OpenClaw adapter adds **EU-max model routing**
on top of governance (on by default). Config keys, profiles, and pricing — and an opt-in
`autostartDaemon` — are in [`adapters/openclaw`](adapters/openclaw).

## Tests

```bash
python3 -m pytest packages/governor_core/tests -q     # core parity tests (no engine needed)
python3 -m pytest adapters/claude-code/tests -q       # Claude Code adapter
cd adapters/openclaw && npm install && npm test       # OpenClaw adapter (TS)
```

## License

[AGPL-3.0-or-later](LICENSE).

## Provenance

The Python core ports the harness-agnostic logic from credence-openclaw (itself
extracted from the Credence engine). credence-openclaw was TypeScript because OpenClaw
plugins are TS; generalising to all coding agents moved the core to Python and the
OpenClaw plugin became one thin adapter among several.
