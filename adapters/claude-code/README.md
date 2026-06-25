# credence-governor — Claude Code adapter

A thin **Claude Code** adapter for [credence-governor](../../README.md): a
`PreToolUse` subprocess hook that Bayesian-governs tool calls (`proceed` /
`block` / `ask`) by asking the governor daemon, which runs the one EU-max reasoner
over the Credence engine.

The adapter carries **no probabilistic code and no feature logic**. Its only job is
to translate Claude Code's native hook events into the harness-neutral wire shape and
render the daemon's decision. Feature & taint extraction is server-side in the daemon
(single-sourced — DRY).

## How it works

```
Claude Code  ──PreToolUse JSON on stdin──▶  credence-governor-claude-code (this hook)
                                                  │  transcript_path JSONL → neutral messages
                                                  ▼  POST /decide  (tool, input, session)
                                            governor daemon (credence-governor-core)
                                                  │  server-side feature/taint extraction
                                                  ▼  one EU-max decision over the skin wire
                                            credence-skin engine (Julia)
        ◀──permissionDecision JSON on stdout──────┘
```

- **`transcript.py`** — replays the session transcript (`transcript_path`) into the
  neutral `messages` list the extractors expect (`user` / `assistant` / `tool_call` /
  `tool_result`). The proposed call — already persisted to the transcript before
  `PreToolUse` fires — is excluded so loop counts see priors only. Sidechain
  (subagent) turns are excluded by default.
- **`client.py`** — `POST /decide` (stdlib `urllib`).
- **`effectors.py`** — maps the governor action to a `PreToolUse` decision.
- **`hook.py`** — the entry point (`credence-governor-claude-code`).

## Overlay semantics (the governor never weakens the host)

| governor action | Claude Code decision | effect |
|---|---|---|
| `proceed` | *(nothing emitted)* | defer to Claude Code's own permission rules |
| `block`   | `deny` + reason | refuse regardless of native rules |
| `ask`     | `ask` + reason | force a user prompt even if native rules would auto-allow |

`permissionDecision: "allow"` is **never** emitted — that would bypass Claude Code's
own safety prompts. The governor can only *add* friction, not remove it.

**Fail-open is absolute.** A malformed event, a daemon that is down, a timeout, or any
error prints nothing and exits 0 — the call proceeds through Claude Code's normal
flow. Run with `CREDENCE_GOVERNOR_DEBUG=1` to log decisions/failures to stderr.

## Capability boundary (Claude Code, hook transport)

| Dimension | Supported |
|---|---|
| Waste gating (loops / repetition) | ✅ |
| Safety (taint-flow / exfil / injected imperatives) | ✅ |
| Routing / model selection | ❌ (no model-resolve hook) |
| Cost / dollars-saved | ◑ observe-only |
| Online ask-response learning | ◌ deferred — see below |

v1 gates **`PreToolUse` only**. `PostToolUse` / `UserPromptSubmit` are intentionally
not wired: neither carries a clean approval label, and treating "the call completed"
as belief evidence would be a second learning path (a constitutional violation), not
just a weak one. The warm-trained brain governs; the daemon logs every decision.
Online ask-learning on Claude Code (inferring the user's reply from the next
transcript turn) is an open design question, deferred.

## Install

**1. Start the daemon** — every adapter shares one local daemon; see the
[core README](../../packages/governor_core) or the
[repo quickstart](../../README.md#install). In short:

```bash
pip install credence-governor-core   # pulls credence-skin-client
credence-governor-daemon             # zero-config: auto-runs the engine via docker/podman
#   overrides: CREDENCE_ENGINE_DIR=~/git/credence  (dev checkout)  ·  CREDENCE_SKIN_COMMAND=…  (pin a digest)
```

> ⚠️ **The daemon is required — the hook does nothing without it.** The hook *fails
> open*: with nothing listening on `:8787`, every tool call just proceeds, so you get
> **no governance and no error**. Confirm the daemon is up with
> `curl -s localhost:8787/ready`, and run a session with `CREDENCE_GOVERNOR_DEBUG=1` to
> watch each decision (and any fail-open) on stderr. The plugin is only the thin hook;
> install it *and* run the daemon. The bundled **SessionStart hook** warns you at the
> start of every session if the daemon is down (and can auto-start it — see below), so
> the no-op state is never silent.

**2. Register the hook** — two ways; both end at the same `PreToolUse` hook.

### Method A — as a Claude Code plugin (recommended; no `pip install`)

The hook is pure stdlib, so the plugin **bundles** it and runs it via
`${CLAUDE_PLUGIN_ROOT}` — there's nothing to `pip install`. Three ways, pick one:

**a. Zero-touch — declare it in `settings.json`.** Add this to `~/.claude/settings.json`
(user scope, all projects); Claude Code registers the marketplace *and* enables the
plugin at next start, no `/plugin` interaction:

```json
{
  "extraKnownMarketplaces": {
    "credence-governor": {
      "source": { "source": "github", "repo": "gfrmin/credence-governor" }
    }
  },
  "enabledPlugins": {
    "credence-governor-claude-code@credence-governor": true
  }
}
```

Put the same block in a project's `.claude/settings.json` to offer it to everyone who
trusts that repo.

**b. One command.** Add the marketplace, then install:

```
/plugin marketplace add gfrmin/credence-governor
/plugin install credence-governor-claude-code@credence-governor
```

(From the shell instead: `claude plugin install
credence-governor-claude-code@credence-governor`. `--scope project|local` to scope it.)

**c. Interactive.** `/plugin marketplace add gfrmin/credence-governor`, then open
`/plugin`, find **credence-governor-claude-code** in the Discover list, and install it.

Run `/reload-plugins` to activate in the current session (it's on automatically in new
ones); manage or remove it from the `/plugin` menu. The plugin reuses the *same*
`credence_governor_claude_code` package this directory ships — `plugin_hook.py` is a
thin launcher that puts it on `sys.path` and calls the same entry point the pip console
script uses (one implementation, two install paths). Manifests:
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json),
[`hooks/hooks.json`](hooks/hooks.json), and the repo-root
[`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json).

### Method B — as a pip package + settings hook

If you'd rather manage it with pip (or script the registration):

```bash
pip install credence-governor-claude-code
credence-governor-cc-install               # → ~/.claude/settings.json  (idempotent)
#   --project   → ./.claude/settings.json   ·   --uninstall → remove
```

Either way the hook has **no runtime dependencies** (pure stdlib); `credence-governor-core`
is needed only for the daemon and the parity test. Static config example:
[`settings.example.json`](settings.example.json).

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `CREDENCE_GOVERNOR_URL` | `http://127.0.0.1:8787` | governor daemon base URL |
| `CREDENCE_GOVERNOR_TIMEOUT` | `5.0` | per-call `/decide` timeout (s); on timeout → fail open |
| `CREDENCE_GOVERNOR_PROFILE` | *(none)* | utility profile passed to the daemon (e.g. `flow-guard`) |
| `CREDENCE_GOVERNOR_DEBUG` | *(off)* | log decisions/failures to stderr |
| `CREDENCE_GOVERNOR_AUTOSTART` | *(off)* | truthy → the SessionStart hook auto-starts the daemon (detached) if it's down |
| `CREDENCE_GOVERNOR_AUTOSTART_WAIT` | `8.0` | post-autostart `/ready` poll budget (s) before reporting STARTING |
| `CREDENCE_GOVERNOR_READY_TIMEOUT` | `1.5` | SessionStart `/ready` probe timeout (s) |

### SessionStart hook (daemon-down warning + opt-in autostart)

Alongside the `PreToolUse` gate, the plugin registers a **`SessionStart`** hook
(`plugin_session_start.py`). At the start of every session it probes `GET /ready`:

- **daemon up** → silent (no spam).
- **daemon down** → a `systemMessage` warns *you* and `additionalContext` tells *Claude*
  that this session is ungoverned (fail-open), with the exact start command — the no-op
  state is never silent.
- **`CREDENCE_GOVERNOR_AUTOSTART=1` + down** → spawns `credence-governor-daemon` detached
  (idempotent — keyed off `/ready`, so a concurrent harness can't double-start it), polls
  briefly, and reports `ONLINE` / `STARTING`. Default-OFF, because booting the engine is
  heavyweight (~18s) and the daemon is shared across harnesses.

The pip path registers both hooks too (`credence-governor-cc-install`).

## Tests

```bash
python -m pytest tests -q
```

Pure-stdlib at runtime; the round-trip parity test (`test_roundtrip.py`) imports
`credence-governor-core` to assert the wire payload deserialises through the daemon's
`event_and_session_from_payload` to the Session the extractors expect — it is skipped
if the core isn't importable.
